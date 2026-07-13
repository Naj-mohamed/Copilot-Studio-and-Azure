"""
Configuration loader for the SharePoint → Azure AI Search connector
(Pattern A — unified multimodal).

Embedding service — one of:
  * Azure OpenAI text-embedding-3-large + GPT-4o captioning (recommended;
    available in Canada Central and most Azure regions). Set AZURE_OPENAI_ENDPOINT.
  * Azure AI Vision Florence multimodal 4.0 (legacy; NOT available in Canada
    Central). Set MULTIMODAL_ENDPOINT. Text and image vectors share the same
    1024-d space.

Azure OpenAI takes priority when AZURE_OPENAI_ENDPOINT is set. At least one
embedding endpoint must be configured.

Authentication everywhere via DefaultAzureCredential (managed identity in prod,
Azure CLI for local dev). Optional CLIENT_SECRET fallback for Graph, resolved
from Key Vault via @Microsoft.KeyVault(...) app-setting reference.
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_required(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(f"Missing required environment variable: {key}")
    return value


def _get_optional(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _get_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ProcessingMode(str, Enum):
    FULL = "full"
    SINCE_DATE = "since-date"
    SINCE_LAST_RUN = "since-last-run"


class FunctionProcessingMode(str, Enum):
    QUEUE = "queue"
    INLINE = "inline"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EntraConfig:
    tenant_id: str
    client_id: str = ""
    client_secret: str = ""

    @property
    def use_managed_identity(self) -> bool:
        return not self.client_secret


@dataclass(frozen=True)
class SharePointConfig:
    site_url: str
    libraries: list[str] = field(default_factory=list)
    # When True, the indexer downloads the latest *published major* version
    # (e.g. 2.0) of each file instead of the current item content, which for
    # libraries with draft/minor versioning would otherwise return the latest
    # unpublished draft (e.g. 2.3). Files that have no published major version
    # yet (drafts only) fall back to the current content.
    published_versions_only: bool = False

    @property
    def hostname(self) -> str:
        return urlparse(self.site_url).hostname or ""

    @property
    def site_path(self) -> str:
        return urlparse(self.site_url).path.rstrip("/")


@dataclass(frozen=True)
class SearchConfig:
    endpoint: str
    index_name: str


@dataclass(frozen=True)
class MultimodalConfig:
    """Azure AI Vision multimodal embeddings (Florence) — 1024d vectors for
    text AND images in the same space.

    Must be populated for the indexer to produce any vectors.
    """
    endpoint: str                          # e.g. https://<foundry>.cognitiveservices.azure.com
    model_version: str = "2023-04-15"
    images_container: str = "images"

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint)


@dataclass(frozen=True)
class DocIntelConfig:
    """Azure AI Document Intelligence (Layout) — optional structural extractor.

    When set, supported formats (PDF, DOCX, PPTX, XLSX, images) go through the
    prebuilt-layout model for reading-order paragraphs, tables, and figures with
    bounding polygons. When empty, the hand-written extractors are used for all
    formats; image files are embedded directly without layout metadata.
    """
    endpoint: str = ""
    skip_below_kb: int = 5
    max_image_size_mb: int = 20
    # Segment large PDFs into page-range batches to avoid the function timeout on
    # dense documents. 0 disables segmentation (whole document in one call).
    page_batch_size: int = 0
    # How many page-range batches to analyse concurrently.
    page_batch_concurrency: int = 4

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint)


@dataclass(frozen=True)
class SpeechTranscriptionConfig:
    """Azure AI Speech Fast Transcription — video/audio transcription.

    Replaces Azure AI Content Understanding (prebuilt-videoSearch), which is
    not available in Canada Central.  Reuses the same Foundry / AIServices
    endpoint set via ``AZURE_OPENAI_ENDPOINT`` — no extra resource needed.

    When ``endpoint`` is set (it defaults to the Azure OpenAI endpoint),
    video files (.mp4, .mov, …) are transcribed by the Azure Speech Fast
    Transcription API into timestamped TEXT blocks, which flow through the
    same chunk/embed/index path as documents.  When empty, video files are
    skipped.
    """
    endpoint: str = ""
    locale: str = "en-US"
    api_version: str = "2024-11-15"
    segment_seconds: int = 60  # group transcript phrases into N-second windows

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint)


@dataclass(frozen=True)
class AzureOpenAIConfig:
    """Azure OpenAI embedding + optional GPT-4o image captioning.

    Preferred embedding path for regions without Florence (e.g. Canada Central).
    When enabled (non-empty endpoint), the indexer uses text-embedding-3-large
    for text and image chunks (images are first described by gpt-4o when
    vision_model is set). Takes priority over MultimodalConfig.
    """
    endpoint: str = ""                         # e.g. https://<foundry>.cognitiveservices.azure.com
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 3072
    vision_model: str = "gpt-4o"               # empty = skip captioning, use neighbour_text only
    api_version: str = "2024-12-01-preview"
    max_concurrency: int = 8

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint)


@dataclass(frozen=True)
class MetadataFilterConfig:
    """SharePoint column-value filter applied at dispatch/indexing time.

    When one or more filters are configured, only files where ALL listed
    SharePoint column values match are dispatched for indexing. Files that
    don't match are silently skipped at the listing stage — no download,
    no embedding, no index entry.

    Column names are the *internal* SharePoint column names (the programmatic
    name, which may differ from the display label shown in the UI). For a
    column displayed as "Document Status" the internal name is often
    ``DocumentStatusTX`` — check the column settings in SharePoint to confirm.

    Values are compared case-insensitively.

    Each condition supports two operators:
      * ``=``  — column equals value (the default)
      * ``<>`` or ``!=`` — column does NOT equal value (exclusion)

    Values may be wrapped in single or double quotes so they can contain
    spaces (e.g. ``FileName<>"Main Document.docx"``); the surrounding quotes
    are stripped during parsing.

    Configured via ``METADATA_FILTERS=col1=val1,col2<>val2`` (comma-separated
    conditions; ALL must match). An empty string disables filtering.

    Each entry is stored as ``(column, op, value)`` where ``op`` is normalised
    to either ``"="`` or ``"<>"``. A two-element ``(column, value)`` entry is
    accepted and treated as an equality condition.
    """
    filters: tuple[tuple[str, str, str], ...] = ()

    def __post_init__(self):
        # Normalise any legacy 2-tuple (column, value) entries to the
        # 3-tuple (column, "=", value) form so consumers can rely on a
        # consistent shape.
        normalised = tuple(
            f if len(f) == 3 else (f[0], "=", f[1]) for f in self.filters
        )
        object.__setattr__(self, "filters", normalised)

    @property
    def enabled(self) -> bool:
        return bool(self.filters)


@dataclass(frozen=True)
class IndexerConfig:
    indexed_extensions: list[str] = field(default_factory=lambda: [
        ".pdf", ".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm",
        ".txt", ".md", ".csv", ".json", ".xml", ".kml",
        ".html", ".htm",
        ".rtf", ".eml", ".epub", ".msg",
        ".vsdx", ".vsd",
        ".odt", ".ods", ".odp",
        ".zip", ".gz",
        ".png", ".jpg", ".jpeg", ".tiff", ".bmp",
        ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v", ".webm",
    ])
    chunk_size: int = 2000
    chunk_overlap: int = 200
    max_concurrency: int = 4
    max_file_size_mb: int = 500
    processing_mode: ProcessingMode = ProcessingMode.SINCE_LAST_RUN
    start_date: datetime | None = None
    function_processing_mode: FunctionProcessingMode = FunctionProcessingMode.QUEUE
    extract_images: bool = True
    # Per-file chunk vectorisation concurrency. The ceiling is also bounded by
    # MultimodalEmbeddingsClient's own semaphore (MULTIMODAL_MAX_IN_FLIGHT).
    vectorise_concurrency: int = 8
    # Optional folder paths inside each library to scope the indexer to.
    # Empty = whole library. Paths are relative to the drive root
    # (e.g. "Finance/Reports,HR/Policies").
    root_paths: list[str] = field(default_factory=list)
    # Periodic full reconciliation cadence (only when not running in FULL mode).
    # Every Nth run compares the index to SharePoint and removes orphans.
    # 0 = disabled.
    reconcile_every_n_runs: int = 24
    # Freshness skip relocated from the worker to the dispatcher: when True, the
    # dispatcher checks each enumerated file against the index and skips
    # enqueuing ones already indexed with a matching lastModified. This keeps a
    # FULL / since-date pass from queuing the thousands of files that are already
    # indexed — only new/changed files are dispatched. Default True.
    dispatcher_skip_fresh: bool = True


@dataclass(frozen=True)
class AppConfig:
    entra: EntraConfig
    sharepoint: SharePointConfig
    search: SearchConfig
    multimodal: MultimodalConfig
    docintel: DocIntelConfig
    speech_transcription: SpeechTranscriptionConfig
    azure_openai: AzureOpenAIConfig
    metadata_filter: MetadataFilterConfig
    indexer: IndexerConfig


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _parse_start_date(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as e:
        raise EnvironmentError(f"START_DATE is not a valid ISO-8601 date: {raw!r} ({e})") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _resolve_processing_mode() -> tuple[ProcessingMode, datetime | None]:
    raw_mode = _get_optional("PROCESSING_MODE").strip().lower()

    legacy = _get_optional("INCREMENTAL_MINUTES")
    if raw_mode == "" and legacy != "":
        logger.warning(
            "INCREMENTAL_MINUTES is deprecated; use PROCESSING_MODE=full|since-date|since-last-run."
        )
        try:
            minutes = int(legacy)
        except ValueError:
            minutes = 0
        return (ProcessingMode.FULL if minutes == 0 else ProcessingMode.SINCE_LAST_RUN, None)

    if raw_mode == "":
        return (ProcessingMode.SINCE_LAST_RUN, None)

    try:
        mode = ProcessingMode(raw_mode)
    except ValueError as e:
        raise EnvironmentError(
            f"PROCESSING_MODE must be one of {[m.value for m in ProcessingMode]}, got {raw_mode!r}"
        ) from e

    start_date = _parse_start_date(_get_optional("START_DATE"))
    if mode == ProcessingMode.SINCE_DATE and start_date is None:
        raise EnvironmentError("PROCESSING_MODE=since-date requires START_DATE (ISO-8601 UTC).")
    return (mode, start_date)


def _strip_quotes(value: str) -> str:
    """Remove a single pair of matching surrounding quotes, if present."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _parse_metadata_filters(raw: str) -> MetadataFilterConfig:
    """Parse ``col=val,col<>val`` into a MetadataFilterConfig.

    Supported operators (checked in this order so they don't collide with the
    plain ``=`` split): ``<>`` and ``!=`` for not-equal, ``=`` for equal.
    Values may be wrapped in single/double quotes to allow spaces; the quotes
    are stripped. Whitespace around column names and values is stripped.
    Empty or malformed tokens are silently ignored.
    """
    if not raw.strip():
        return MetadataFilterConfig()
    filters: list[tuple[str, str, str]] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue

        if "<>" in token:
            col, _, val = token.partition("<>")
            op = "<>"
        elif "!=" in token:
            col, _, val = token.partition("!=")
            op = "<>"
        elif "=" in token:
            col, _, val = token.partition("=")
            op = "="
        else:
            logger.warning(
                f"METADATA_FILTERS: ignoring malformed token {token!r} "
                "(expected col=value, col<>value, or col!=value)"
            )
            continue

        col = col.strip()
        val = _strip_quotes(val.strip())
        if col and val:
            filters.append((col, op, val))
        else:
            logger.warning(f"METADATA_FILTERS: ignoring empty column or value in {token!r}")
    return MetadataFilterConfig(filters=tuple(filters))


def load_config() -> AppConfig:
    libraries_raw = _get_optional("SHAREPOINT_LIBRARIES", "")
    libraries = [lib.strip() for lib in libraries_raw.split(",") if lib.strip()] if libraries_raw else []

    root_paths_raw = _get_optional("SHAREPOINT_ROOT_PATHS", "")
    root_paths = [p.strip().lstrip("/") for p in root_paths_raw.split(",") if p.strip()] if root_paths_raw else []

    extensions_raw = _get_optional(
        "INDEXED_EXTENSIONS",
        ".pdf,.docx,.docm,.xlsx,.xlsm,.pptx,.pptm,.txt,.md,.csv,.json,.xml,.kml,"
        ".html,.htm,.rtf,.eml,.epub,.msg,.vsdx,.vsd,.odt,.ods,.odp,.zip,.gz,"
        ".png,.jpg,.jpeg,.tiff,.bmp,"
        ".mp4,.mov,.avi,.mkv,.wmv,.m4v,.webm"
    )
    extensions = [ext.strip() for ext in extensions_raw.split(",") if ext.strip()]

    mode, start_date = _resolve_processing_mode()

    fn_mode_raw = _get_optional("FUNCTION_PROCESSING_MODE", "queue").strip().lower()
    try:
        fn_mode = FunctionProcessingMode(fn_mode_raw)
    except ValueError as e:
        raise EnvironmentError(
            f"FUNCTION_PROCESSING_MODE must be one of {[m.value for m in FunctionProcessingMode]}, "
            f"got {fn_mode_raw!r}"
        ) from e

    # Embedding endpoint validation: at least one must be configured.
    azure_openai_ep = _get_optional("AZURE_OPENAI_ENDPOINT", "")
    multimodal_ep = _get_optional("MULTIMODAL_ENDPOINT", "")
    if not azure_openai_ep and not multimodal_ep:
        raise EnvironmentError(
            "At least one embedding endpoint is required. "
            "Set AZURE_OPENAI_ENDPOINT (recommended, works in all regions) "
            "or MULTIMODAL_ENDPOINT (Azure AI Vision Florence — not available in all regions)."
        )

    return AppConfig(
        entra=EntraConfig(
            tenant_id=_get_required("TENANT_ID"),
            client_id=_get_optional("CLIENT_ID"),
            client_secret=_get_optional("CLIENT_SECRET"),
        ),
        sharepoint=SharePointConfig(
            site_url=_get_required("SHAREPOINT_SITE_URL"),
            libraries=libraries,
            published_versions_only=_get_bool("PUBLISHED_VERSIONS_ONLY", False),
        ),
        search=SearchConfig(
            endpoint=_get_required("SEARCH_ENDPOINT"),
            index_name=_get_optional("SEARCH_INDEX_NAME", "sharepoint-index"),
        ),
        multimodal=MultimodalConfig(
            endpoint=multimodal_ep,
            model_version=_get_optional("MULTIMODAL_MODEL_VERSION", "2023-04-15"),
            images_container=_get_optional("IMAGES_CONTAINER", "images"),
        ),
        azure_openai=AzureOpenAIConfig(
            endpoint=azure_openai_ep,
            embedding_model=_get_optional("AZURE_OPENAI_EMBEDDING_MODEL", "text-embedding-3-large"),
            embedding_dimensions=int(_get_optional("AZURE_OPENAI_EMBEDDING_DIMENSIONS", "3072")),
            vision_model=_get_optional("AZURE_OPENAI_VISION_MODEL", "gpt-4o"),
            api_version=_get_optional("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
            max_concurrency=int(_get_optional("AZURE_OPENAI_MAX_IN_FLIGHT", "8")),
        ),
        metadata_filter=_parse_metadata_filters(
            _get_optional("METADATA_FILTERS", "")
        ),
        docintel=DocIntelConfig(
            endpoint=_get_optional("DOCINTEL_ENDPOINT", ""),
            skip_below_kb=int(_get_optional("DOCINTEL_SKIP_BELOW_KB", "5")),
            max_image_size_mb=int(_get_optional("DOCINTEL_MAX_IMAGE_SIZE_MB", "20")),
            page_batch_size=int(_get_optional("DOCINTEL_PAGE_BATCH_SIZE", "0")),
            page_batch_concurrency=int(_get_optional("DOCINTEL_PAGE_BATCH_CONCURRENCY", "4")),
        ),
        speech_transcription=SpeechTranscriptionConfig(
            endpoint=azure_openai_ep,  # reuse Foundry/AIServices endpoint
            locale=_get_optional("SPEECH_LOCALE", "en-US"),
            api_version=_get_optional("SPEECH_API_VERSION", "2024-11-15"),
            segment_seconds=int(_get_optional("SPEECH_SEGMENT_SECONDS", "60")),
        ),
        indexer=IndexerConfig(
            indexed_extensions=extensions,
            chunk_size=int(_get_optional("CHUNK_SIZE", "2000")),
            chunk_overlap=int(_get_optional("CHUNK_OVERLAP", "200")),
            max_concurrency=int(_get_optional("MAX_CONCURRENCY", "4")),
            max_file_size_mb=int(_get_optional("MAX_FILE_SIZE_MB", "500")),
            processing_mode=mode,
            start_date=start_date,
            function_processing_mode=fn_mode,
            extract_images=_get_bool("EXTRACT_IMAGES", True),
            vectorise_concurrency=int(_get_optional("VECTORISE_CONCURRENCY", "8")),
            root_paths=root_paths,
            reconcile_every_n_runs=int(_get_optional("RECONCILE_EVERY_N_RUNS", "24")),
            dispatcher_skip_fresh=_get_bool("DISPATCHER_SKIP_FRESH", True),
        ),
    )
