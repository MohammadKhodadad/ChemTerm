"""High-precision deterministic terminology rules."""

from __future__ import annotations

import re
from collections.abc import Iterator

from chemterm.contracts.extraction import CandidateType, RawCandidate

_ELEMENT_SYMBOLS = frozenset(
    """
    H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni
    Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe
    Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg
    Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg
    Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og
    """.split()  # noqa: SIM905 - the compact periodic table is easier to audit
)
_FORMULA = re.compile(r"\b(?:[A-Z][a-z]?[0-9]*){2,}\b")
_FORMULA_TOKEN = re.compile(r"([A-Z][a-z]?)([0-9]*)")
_INCHI = re.compile(r"\bInChI=[^\s,;]+")
_INCHI_KEY = re.compile(r"\b[A-Z]{14}-[A-Z]{10}-[A-Z]\b")
_CAS_RN = re.compile(r"\b[1-9][0-9]{1,6}-[0-9]{2}-[0-9]\b")
_SMILES = re.compile(r"(?i:\bSMILES\s*[:=]\s*)(?P<value>[^\s,;]+)")
_QUANTITY = re.compile(
    r"(?<![\w.])(?:\d+(?:\.\d+)?\s*(?:-|–|to)\s*)?\d+(?:\.\d+)?\s*"
    r"(?:°C|°F|K|wt\.?%|vol\.?%|mol%|%|ppm|ppb|mol|mmol|μmol|µmol|"
    r"kg|mg|μg|µg|g|mL|μL|µL|L|MPa|kPa|Pa|mbar|bar|M|mM|μM|µM|"
    r"nm|μm|µm|mm|cm|mPa[·.]s)(?=$|[\s,;.)])"
)
_PH = re.compile(r"\bpH(?:\s*(?:of|=|:))?\s*\d+(?:\.\d+)?(?:\s*(?:-|–|to)\s*\d+(?:\.\d+)?)?")
_PATENT_LABEL = re.compile(
    r"\b(?:Compound|Intermediate|Example|Preparation)\s+[A-Z]?[0-9]+[A-Za-z]?\b",
    re.IGNORECASE,
)
_ABBREVIATION = re.compile(r"\((?P<abbr>[A-Z][A-Z0-9-]{1,10})\)")


class DeterministicRuleExtractor:
    """Extract formulas, identifiers, measurements, and patent labels."""

    name = "deterministic_rules"
    version = "1.0"

    def extract(self, text: str) -> tuple[RawCandidate, ...]:
        """Return non-overwriteable raw rule predictions."""

        candidates = [
            *self._matches(
                text,
                _INCHI_KEY,
                CandidateType.CHEMICAL_ENTITY,
                "INCHI_KEY",
                0.99,
            ),
            *self._matches(
                text,
                _INCHI,
                CandidateType.CHEMICAL_ENTITY,
                "INCHI",
                0.99,
            ),
            *self._cas_numbers(text),
            *self._smiles(text),
            *self._matches(
                text,
                _QUANTITY,
                CandidateType.MEASUREMENT,
                "QUANTITY",
                0.98,
            ),
            *self._matches(
                text,
                _PH,
                CandidateType.MEASUREMENT,
                "PH",
                0.98,
            ),
            *self._matches(
                text,
                _PATENT_LABEL,
                CandidateType.OTHER_TECHNICAL_CONCEPT,
                "PATENT_LABEL",
                0.90,
            ),
            *self._abbreviations(text),
            *self._formulas(text),
        ]
        return tuple(
            sorted(candidates, key=lambda item: (item.start, item.end, item.raw_label or ""))
        )

    def _cas_numbers(self, text: str) -> Iterator[RawCandidate]:
        for match in _CAS_RN.finditer(text):
            value = match.group(0)
            digits = value.replace("-", "")
            checksum = (
                sum(
                    int(digit) * weight
                    for weight, digit in enumerate(reversed(digits[:-1]), start=1)
                )
                % 10
            )
            if checksum != int(digits[-1]):
                continue
            yield RawCandidate(
                text=value,
                start=match.start(),
                end=match.end(),
                types=(CandidateType.CHEMICAL_ENTITY,),
                confidence=0.99,
                extractor=self.name,
                extractor_version=self.version,
                raw_label="CAS_RN",
            )

    def _smiles(self, text: str) -> Iterator[RawCandidate]:
        for match in _SMILES.finditer(text):
            start, end = match.span("value")
            yield RawCandidate(
                text=match.group("value"),
                start=start,
                end=end,
                types=(CandidateType.CHEMICAL_ENTITY,),
                confidence=0.98,
                extractor=self.name,
                extractor_version=self.version,
                raw_label="SMILES",
            )

    def _matches(
        self,
        text: str,
        pattern: re.Pattern[str],
        candidate_type: CandidateType,
        raw_label: str,
        confidence: float,
    ) -> Iterator[RawCandidate]:
        for match in pattern.finditer(text):
            yield RawCandidate(
                text=match.group(0),
                start=match.start(),
                end=match.end(),
                types=(candidate_type,),
                confidence=confidence,
                extractor=self.name,
                extractor_version=self.version,
                raw_label=raw_label,
            )

    def _formulas(self, text: str) -> Iterator[RawCandidate]:
        for match in _FORMULA.finditer(text):
            symbols = [item.group(1) for item in _FORMULA_TOKEN.finditer(match.group(0))]
            if len(symbols) < 2 or any(symbol not in _ELEMENT_SYMBOLS for symbol in symbols):
                continue
            yield RawCandidate(
                text=match.group(0),
                start=match.start(),
                end=match.end(),
                types=(CandidateType.CHEMICAL_ENTITY,),
                confidence=0.92,
                extractor=self.name,
                extractor_version=self.version,
                raw_label="MOLECULAR_FORMULA",
            )

    def _abbreviations(self, text: str) -> Iterator[RawCandidate]:
        for match in _ABBREVIATION.finditer(text):
            start, end = match.span("abbr")
            yield RawCandidate(
                text=match.group("abbr"),
                start=start,
                end=end,
                types=(CandidateType.OTHER_TECHNICAL_CONCEPT,),
                confidence=0.85,
                extractor=self.name,
                extractor_version=self.version,
                raw_label="ABBREVIATION",
                needs_review=True,
            )
