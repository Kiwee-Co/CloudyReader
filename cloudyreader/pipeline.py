"""Pipeline: one paste in, one Reading (script and WAV) out. Every stage is injected."""

from __future__ import annotations

import dataclasses
import logging
import platform
import threading
from collections.abc import Callable, Iterator, Sequence
from typing import Protocol

from cloudyreader.config import Settings, load_settings
from cloudyreader.models import (
    Audio,
    EntityDetector,
    EntitySpan,
    Normalizer,
    Parser,
    Question,
    Reading,
    RenderOptions,
    Resolution,
    Resolver,
    SpokenScript,
    TtsEngine,
    VoiceInfo,
)

log = logging.getLogger(__name__)

# The CRAFT model tags both words here; the regex detectors tag neither.
NER_PROBE = "Insulin is secreted by beta cells in response to glucose."


class SpeechService(Protocol):
    """What the pipeline needs from `cloudyreader.tts.TtsService`.

    Optional engine notes: `last_warnings` (set by each synthesize) and `script_warnings(...)`.
    """

    def voices(self) -> list[VoiceInfo]: ...
    def synthesize(self, script: SpokenScript, voice: VoiceInfo, opts: RenderOptions) -> Audio: ...


class Pipeline:
    """ReaderService: parse, detect entities, resolve them, normalize, synthesize.

    R5: resolutions only travel to the normalizer, which decides HOW a token is said. This class
    never reads a resolved name and never edits the questions or the script.
    """

    def __init__(
        self,
        *,
        parser: Parser,
        detector: EntityDetector,
        resolver: Resolver,
        normalizer: Normalizer,
        tts: SpeechService,
        settings: Settings,
        offline_resolver: Resolver | None = None,
    ) -> None:
        self._parser = parser
        self._detector = detector
        self._resolver = resolver
        self._offline_resolver = offline_resolver
        self._normalizer = normalizer
        self._tts = tts
        self._settings = settings
        self._start_preload()

    def voices(self) -> list[VoiceInfo]:
        return self._tts.voices()

    def entity_mode(self) -> str:
        """ "ner" when the detector tags NER_PROBE with its model, else "regex-only"."""
        spans = self._detector.detect(NER_PROBE)
        return "ner" if any(span.source == "ner" for span in spans) else "regex-only"

    def prepare(self, raw: str, voice_key: str, opts: RenderOptions) -> Reading:
        if not raw.strip():
            raise ValueError("nothing to read")
        voice = self._find_voice(voice_key)  # before any lookup: a wrong key must fail fast
        questions = self._parser.parse(raw)
        if not questions:
            raise ValueError("nothing to read")
        notes: list[str] = []
        entities = self._detect(questions, opts, notes)
        resolutions = self._resolve(entities, opts, notes)
        script = self._normalizer.to_script(questions, resolutions, opts)
        audio = self._tts.synthesize(script, voice, opts)
        # Snapshot at once: the next synthesize() on a shared service overwrites it.
        spoken = tuple(getattr(self._tts, "last_warnings", None) or ())
        notes.extend(script.warnings)
        notes.extend(spoken)
        engine_notes = self._engine_notes(script, voice, notes)
        notes.extend(engine_notes)
        return Reading(
            questions=tuple(questions),
            script=script,
            entities=tuple(entities),
            resolutions=resolutions,
            audio=audio,
            warnings=tuple(dict.fromkeys(notes)),
        )

    def _find_voice(self, key: str) -> VoiceInfo:
        voices = self._tts.voices()
        for voice in voices:
            if voice.key == key:
                if not voice.installed:
                    raise ValueError(f"voice {key!r} is not installed")
                return voice
        known = ", ".join(voice.key for voice in voices) or "none"
        raise ValueError(f"unknown voice {key!r} (available: {known})")

    def _detect(
        self, questions: Sequence[Question], opts: RenderOptions, notes: list[str]
    ) -> list[EntitySpan]:
        def scan() -> list[EntitySpan]:
            return [
                span for text in _fields(questions, opts) for span in self._detector.detect(text)
            ]

        return _best_effort("entity detection", scan, [], notes)

    def _resolve(
        self, entities: Sequence[EntitySpan], opts: RenderOptions, notes: list[str]
    ) -> dict[str, Resolution]:
        first_seen: dict[str, EntitySpan] = {}
        for span in entities:
            first_seen.setdefault(span.text, span)
        online = opts.online_lookups and not self._settings.offline
        resolver = self._resolver if online else self._offline_resolver
        if resolver is None or not first_seen:
            return {}
        spans = list(first_seen.values())
        budget = self._settings.lookup_budget_s

        def lookup() -> dict[str, Resolution]:
            return dict(resolver.resolve_many(spans, timeout_s=budget))

        return _best_effort("name lookup", lookup, {}, notes)

    def _engine_notes(
        self, script: SpokenScript, voice: VoiceInfo, notes: list[str]
    ) -> tuple[str, ...]:
        hook = getattr(self._tts, "script_warnings", None)
        if hook is None:
            return ()
        return _best_effort("pronunciation check", lambda: tuple(hook(script, voice)), (), notes)

    def _start_preload(self) -> None:
        preload = getattr(self._detector, "preload", None)
        if preload is None:
            return
        # preload() may block, so it gets its own thread: building the service must stay instant.
        thread = threading.Thread(
            target=_run_preload, args=(preload,), name="cloudyreader-preload", daemon=True
        )
        thread.start()


def _fields(questions: Sequence[Question], opts: RenderOptions) -> Iterator[str]:
    """The text that will be spoken: stems and choices, plus the answer only when it is read."""
    for question in questions:
        yield question.stem
        for choice in question.choices:
            yield choice.text
        if opts.read_answer and question.answer:
            yield question.answer


def _best_effort[T](what: str, stage: Callable[[], T], fallback: T, notes: list[str]) -> T:
    """Run a stage that only refines the speech: its failure is logged and reported, not raised."""
    try:
        return stage()
    except Exception as exc:
        log.warning("%s failed, continuing without it: %s", what, exc, exc_info=True)
        notes.append(f"{what} failed ({type(exc).__name__}); continuing without it")
        return fallback


def _run_preload(preload: Callable[[], None]) -> None:
    try:
        preload()
    except Exception as exc:
        log.warning("entity detector preload failed: %s", exc, exc_info=True)


def build_default_service(settings: Settings | None = None) -> Pipeline:
    """Wire the real components. Their imports stay inside, so a bare Pipeline needs none."""
    from cloudyreader.entities import SciEntityDetector
    from cloudyreader.lexicon import Lexicon
    from cloudyreader.normalize import ScriptNormalizer
    from cloudyreader.parser import QuestionParser
    from cloudyreader.resolvers.cache import ResolutionCache
    from cloudyreader.resolvers.chain import ChainResolver
    from cloudyreader.resolvers.http import HttpClient
    from cloudyreader.resolvers.opsin import OpsinResolver
    from cloudyreader.resolvers.pubchem import PubChemResolver
    from cloudyreader.resolvers.uniprot import UniProtResolver
    from cloudyreader.tts import TtsService

    settings = settings or load_settings()
    lexicon = Lexicon.load()
    http = HttpClient(timeout_s=settings.http_timeout_s, max_rps=settings.max_rps)
    shared = {
        "cache": ResolutionCache(settings.cache_dir / "resolutions.sqlite"),
        "opsin": OpsinResolver(),
        "pubchem": PubChemResolver(http),
        "uniprot": UniProtResolver(http),
        "skip": lambda token: lexicon.lookup(token) is not None,
    }
    return Pipeline(
        parser=QuestionParser(),
        detector=SciEntityDetector(),
        resolver=ChainResolver(settings=settings, **shared),
        offline_resolver=ChainResolver(
            settings=dataclasses.replace(settings, offline=True), **shared
        ),
        normalizer=ScriptNormalizer(lexicon),
        tts=TtsService(_engines(settings), settings.cache_dir / "wav"),
        settings=settings,
    )


def _engines(settings: Settings) -> list[TtsEngine]:
    from cloudyreader.engines.piper import PiperEngine

    engines: list[TtsEngine] = [PiperEngine(settings.voices_dir)]
    if platform.machine() == "arm64":
        try:
            from cloudyreader.engines.kokoro import KokoroEngine
        except ImportError as exc:  # no MLX stack: Piper alone still reads
            log.info("Kokoro engine not loaded: %s", exc)
        else:
            engines.append(KokoroEngine(settings.models_dir))
    return engines
