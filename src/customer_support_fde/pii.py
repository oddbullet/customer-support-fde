from functools import cache

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine

# Pattern-based entities only. Names, places and dates are left out: dish names
# ("General Tso's chicken", "Peking duck") and pickup times would get redacted.
PII_ENTITIES = [
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "US_SSN",
    "IBAN_CODE",
    "IP_ADDRESS",
]


@cache
def _analyzer() -> AnalyzerEngine:
    # The small spaCy model is enough for pattern recognizers; Presidio's default would
    # download the ~400 MB large model at runtime.
    nlp_engine = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        }
    ).create_engine()
    return AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])


@cache
def _anonymizer() -> AnonymizerEngine:
    return AnonymizerEngine()


def redact(text: str) -> str:
    # Replaces each hit with its entity placeholder, e.g. "<PHONE_NUMBER>".
    results = _analyzer().analyze(text=text, entities=PII_ENTITIES, language="en")
    return _anonymizer().anonymize(text=text, analyzer_results=results).text
