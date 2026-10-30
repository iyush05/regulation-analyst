"""HTTP API for the web frontend.

Single user: one bearer token guards every endpoint except the health check. Slow work (the
agent and ingestion) runs as background jobs on one worker thread, which also serialises
writes to SQLite. Jobs live in memory; ingestion progress itself persists in ingestion_jobs.
"""

import hmac
import re
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .errors import ResearchError
from .models import Basis, Policy, Result, Scope, Trust
from .service import ResearchService
from .store import Store

MAX_UPLOAD_BYTES = 200_000_000


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database: Path
    token: str = Field(min_length=16)
    cors_origins: list[str] = Field(default_factory=list)
    data_dir: Path = Path("data")
    artifacts_dir: Path = Path("artifacts")

    @property
    def paths(self) -> dict:
        return {
            "archive": self.data_dir / "sources",
            "inbox": self.data_dir / "inbox",
            "extractions": self.artifacts_dir / "extractions",
            "candidates": self.artifacts_dir / "candidates",
        }


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Scope = "consolidated"
    basis: Basis = "Ind AS"
    policy: Policy = "latest_available"
    trust: Trust = "allow_automated"


class AskRequest(Selection):
    question: str = Field(min_length=1, max_length=2000)


class CompareRequest(Selection):
    metric: str
    companies: list[str] = Field(min_length=2, max_length=10)
    years: list[str] = Field(min_length=1, max_length=10)


class AgentRequest(AskRequest):
    allow_ingest: bool = False
    llm_resolve: bool = False


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company: str = Field(min_length=2, max_length=200)
    years: list[str] = Field(min_length=1, max_length=3)
    urls: dict[str, str] = Field(default_factory=dict)
    llm_resolve: bool = False
    remap: bool = False


class Job(BaseModel):
    id: str
    kind: Literal["agent", "ingest"]
    status: Literal["queued", "running", "done", "failed"]
    request: dict
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    result: dict | None = None
    error: str | None = None
    progress: list[dict] = Field(default_factory=list)


class Jobs:
    def __init__(self):
        self.items: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="job")

    def submit(self, kind, request: dict, work) -> Job:
        job = Job(
            id=uuid.uuid4().hex, kind=kind, status="queued", request=request, created_at=time.time()
        )
        with self.lock:
            self.items[job.id] = job

        def run():
            self.update(job.id, status="running", started_at=time.time())
            try:
                self.update(job.id, status="done", result=work(), finished_at=time.time())
            except Exception as exc:  # A failed job is reported, never raised into the pool.
                message = (
                    str(exc) if isinstance(exc, ResearchError) else f"{type(exc).__name__}: {exc}"
                )
                self.update(job.id, status="failed", error=message, finished_at=time.time())

        self.pool.submit(run)
        return job

    def update(self, job_id, **changes):
        with self.lock:
            self.items[job_id] = self.items[job_id].model_copy(update=changes)

    def get(self, job_id) -> Job:
        with self.lock:
            if job_id not in self.items:
                raise HTTPException(404, "No such job")
            return self.items[job_id]

    def recent(self, limit=20) -> list[Job]:
        with self.lock:
            return sorted(self.items.values(), key=lambda j: j.created_at, reverse=True)[:limit]


def model_provider():
    import os

    from .providers import OpenAIProvider

    return OpenAIProvider(model=os.environ.get("REGULATION_AGENT_MODEL", ""))


def create_app(settings: Settings, *, provider_factory=model_provider, client=None) -> FastAPI:
    """`provider_factory` and `client` let tests replace the model and HTTP downloads."""
    app = FastAPI(
        title="Regulation Analyst API",
        version=__version__,
        description="Source-backed research on Indian company financials.",
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )
    jobs = Jobs()
    bearer = HTTPBearer(auto_error=False)

    def authorised(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ):
        supplied = credentials.credentials if credentials else ""
        if not hmac.compare_digest(supplied.encode(), settings.token.encode()):
            raise HTTPException(401, "Missing or invalid access token")

    def service() -> ResearchService:
        return ResearchService(Store(settings.database))

    def provider():
        try:
            return provider_factory()
        except ResearchError as exc:
            raise HTTPException(503, f"Model not configured: {exc}") from exc

    def answer(result: Result) -> Result:
        if result.status == "invalid_request":
            raise HTTPException(422, result.message)
        return result

    guarded = [Depends(authorised)]

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__, "corpus_version": service().store.version}

    @app.get("/api/companies", dependencies=guarded)
    def companies() -> Result:
        return service().call("list_companies")

    @app.get("/api/companies/{company}/coverage", dependencies=guarded)
    def coverage(company: str, years: Annotated[list[str] | None, Query()] = None) -> Result:
        return answer(service().call("check_coverage", company=company, years=years))

    @app.get("/api/metrics", dependencies=guarded)
    def metrics() -> Result:
        return service().call("list_metrics")

    @app.post("/api/ask", dependencies=guarded)
    def ask(request: AskRequest) -> Result:
        return service().call("answer_question", **request.model_dump())

    @app.post("/api/compare", dependencies=guarded)
    def compare(request: CompareRequest) -> Result:
        return answer(service().call("compare_companies", **request.model_dump()))

    @app.get("/api/sources/{evidence_id}", dependencies=guarded)
    def source(evidence_id: str) -> Result:
        return answer(service().call("get_source", evidence_id=evidence_id))

    @app.get(
        "/api/sources/{evidence_id}/page.png",
        dependencies=guarded,
        response_class=Response,
        responses={200: {"content": {"image/png": {}}}},
    )
    def page_image(evidence_id: str) -> Response:
        """The archived source page with the cited cell outlined."""
        import pymupdf

        store = service().store
        try:
            evidence = store.record("evidence", evidence_id)
            document = store.record("documents", evidence.document_id)
        except ResearchError as exc:
            raise HTTPException(404, str(exc)) from exc
        if not document.snapshot_path or not evidence.pdf_page:
            raise HTTPException(404, "No archived copy of this source page")
        with pymupdf.open(document.snapshot_path) as pdf:
            page = pdf[evidence.pdf_page - 1]
            if evidence.bbox:
                page.draw_rect(pymupdf.Rect(evidence.bbox) + (-2, -2, 2, 2), color=(0.85, 0.1, 0.1))
            png = page.get_pixmap(dpi=110).tobytes("png")
        return Response(png, media_type="image/png", headers={"Cache-Control": "private"})

    def agent_work(request: AgentRequest, model):
        from .agent import Selection as AgentSelection
        from .agent import run_agent
        from .pipeline import agent_ingestor

        ingestor = (
            agent_ingestor(
                settings.database,
                model,
                llm_resolve=request.llm_resolve,
                client=client,
                **settings.paths,
            )
            if request.allow_ingest
            else None
        )
        result = run_agent(
            service(),
            request.question,
            model,
            log_dir=settings.artifacts_dir / "runs",
            selection=AgentSelection(
                scope=request.scope,
                basis=request.basis,
                policy=request.policy,
                trust=request.trust,
            ),
            ingestor=ingestor,
        )
        return result.model_dump(mode="json")

    @app.post("/api/agent", dependencies=guarded, status_code=202)
    def agent(request: AgentRequest) -> Job:
        model = provider()
        return jobs.submit("agent", request.model_dump(), lambda: agent_work(request, model))

    def ingest_work(request: IngestRequest, model):
        from .pipeline import ingest

        result = ingest(
            Store(settings.database, readonly=False),
            request.company,
            request.years,
            provider=model,
            urls=request.urls,
            client=client,
            llm_resolve=request.llm_resolve and model is not None,
            remap=request.remap,
            **settings.paths,
        )
        return result

    def needs_model(request: IngestRequest) -> bool:
        """Discovery needs the model, unless every year has a saved plan or an explicit link."""
        from .models import year_number
        from .pipeline import item_key, saved_plan, slug

        if request.llm_resolve:
            return True
        wanted = {year_number(y) for y in request.years}
        linked = {year_number(y) for y in request.urls}
        _, saved = saved_plan(Store(settings.database), slug(request.company))
        planned = {y for y in wanted if "url" in saved.get(item_key(y), {}).get("detail", {})}
        return not wanted <= linked | planned

    def start_ingest(request: IngestRequest) -> Job:
        model = provider() if needs_model(request) else None
        return jobs.submit("ingest", request.model_dump(), lambda: ingest_work(request, model))

    @app.post("/api/ingest", dependencies=guarded, status_code=202)
    def ingest_company(request: IngestRequest) -> Job:
        return start_ingest(request)

    @app.post("/api/ingest/upload", dependencies=guarded, status_code=202)
    def upload(
        file: Annotated[UploadFile, File()],
        company: Annotated[str, Form(min_length=2)],
        years: Annotated[str, Form(description="Comma-separated, e.g. FY24,FY25")],
    ) -> Job:
        """A PDF the site refused to serve automatically; ingestion resumes with it."""
        inbox = settings.paths["inbox"]
        inbox.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(file.filename or "upload.pdf").name)
        name = name if name.lower().endswith(".pdf") else name + ".pdf"
        with tempfile.NamedTemporaryFile(dir=inbox, suffix=".part", delete=False) as handle:
            temporary = Path(handle.name)
            size = 0
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    temporary.unlink(missing_ok=True)
                    raise HTTPException(413, "PDF exceeds 200 MB")
                handle.write(chunk)
        with temporary.open("rb") as check:
            if b"%PDF-" not in check.read(1024):
                temporary.unlink(missing_ok=True)
                raise HTTPException(422, "Upload is not a PDF")
        shutil.move(temporary, inbox / name)
        wanted = [y.strip() for y in years.split(",") if y.strip()]
        return start_ingest(IngestRequest(company=company, years=wanted))

    @app.get("/api/jobs", dependencies=guarded)
    def recent_jobs() -> list[Job]:
        return jobs.recent()

    @app.get("/api/jobs/{job_id}", dependencies=guarded)
    def job(job_id: str) -> Job:
        current = jobs.get(job_id)
        if current.kind == "ingest":
            from .pipeline import slug

            progress = service().store.jobs(slug(current.request["company"]))
            current = current.model_copy(update={"progress": progress})
        return current

    app.state.jobs = jobs
    return app
