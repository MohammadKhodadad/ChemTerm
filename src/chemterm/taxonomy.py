"""Controlled concept taxonomy and runtime terminology scope."""

from __future__ import annotations

from typing import NamedTuple


class ConceptTypeDefinition(NamedTuple):
    code: str
    label: str
    parent_code: str | None
    description: str


CONCEPT_TYPE_DEFINITIONS: tuple[ConceptTypeDefinition, ...] = (
    ConceptTypeDefinition(
        "CHEMICAL_ENTITY",
        "Chemical entity",
        None,
        "A chemically defined substance, species, or class.",
    ),
    ConceptTypeDefinition(
        "ELEMENT", "Element", "CHEMICAL_ENTITY", "A chemical element or elemental substance."
    ),
    ConceptTypeDefinition(
        "COMPOUND",
        "Compound",
        "CHEMICAL_ENTITY",
        "A specific chemical compound with defined composition or structure.",
    ),
    ConceptTypeDefinition(
        "SALT",
        "Salt",
        "COMPOUND",
        "An ionic salt form distinct from its neutral or parent compound.",
    ),
    ConceptTypeDefinition(
        "SOLVATE",
        "Solvate",
        "COMPOUND",
        "A compound incorporating a defined solvent in its solid form.",
    ),
    ConceptTypeDefinition(
        "HYDRATE", "Hydrate", "SOLVATE", "A solvate whose incorporated solvent is water."
    ),
    ConceptTypeDefinition(
        "POLYMER",
        "Polymer",
        "CHEMICAL_ENTITY",
        "A polymeric substance or chemically defined polymer family.",
    ),
    ConceptTypeDefinition(
        "CHEMICAL_CLASS",
        "Chemical class",
        "CHEMICAL_ENTITY",
        "A class of substances sharing a chemical feature, without denoting one compound.",
    ),
    ConceptTypeDefinition(
        "FUNCTIONAL_GROUP",
        "Functional group",
        "CHEMICAL_ENTITY",
        "A recurring atom group that gives characteristic chemical behavior.",
    ),
    ConceptTypeDefinition(
        "MARKUSH_CLASS",
        "Markush class",
        "CHEMICAL_ENTITY",
        "A patent-defined generic chemical structure covering alternatives.",
    ),
    ConceptTypeDefinition(
        "MATERIAL",
        "Material",
        None,
        "A substance or engineered material identified by composition, structure, "
        "or chemical function.",
    ),
    ConceptTypeDefinition(
        "MIXTURE_OR_COMPOSITION",
        "Mixture or composition",
        None,
        "A formulation, solution, dispersion, blend, or other multi-component composition.",
    ),
    ConceptTypeDefinition(
        "PROCESS",
        "Process",
        None,
        "A chemistry-relevant operation that transforms, treats, separates, "
        "or manufactures matter.",
    ),
    ConceptTypeDefinition(
        "CHEMICAL_REACTION",
        "Chemical reaction",
        "PROCESS",
        "A process involving formation or breaking of chemical bonds.",
    ),
    ConceptTypeDefinition(
        "SYNTHESIS_PROCESS",
        "Synthesis process",
        "PROCESS",
        "A process for preparing a chemical substance or material.",
    ),
    ConceptTypeDefinition(
        "SEPARATION_PROCESS",
        "Separation process",
        "PROCESS",
        "A process that separates substances or material fractions.",
    ),
    ConceptTypeDefinition(
        "MANUFACTURING_PROCESS",
        "Manufacturing process",
        "PROCESS",
        "A chemistry- or materials-relevant production process.",
    ),
    ConceptTypeDefinition(
        "PROPERTY",
        "Property",
        None,
        "A characteristic of a chemical entity, material, mixture, or process.",
    ),
    ConceptTypeDefinition(
        "CHEMICAL_PROPERTY",
        "Chemical property",
        "PROPERTY",
        "A property describing chemical composition, reactivity, or stability.",
    ),
    ConceptTypeDefinition(
        "PHYSICAL_PROPERTY",
        "Physical property",
        "PROPERTY",
        "A measurable physical characteristic of a substance or material.",
    ),
    ConceptTypeDefinition(
        "PERFORMANCE_PROPERTY",
        "Performance property",
        "PROPERTY",
        "A functional performance characteristic of a material, formulation, or process.",
    ),
    ConceptTypeDefinition(
        "MEASUREMENT",
        "Measurement",
        None,
        "A chemistry-relevant measured quantity, condition, unit-bearing value, "
        "or analytical result.",
    ),
    ConceptTypeDefinition(
        "EQUIPMENT",
        "Equipment",
        None,
        "Equipment whose identity is specifically chemical, electrochemical, "
        "analytical, or process-related.",
    ),
    ConceptTypeDefinition(
        "APPLICATION",
        "Application",
        None,
        "A specialized chemical or material use whose chemistry is essential to the concept.",
    ),
    ConceptTypeDefinition(
        "OTHER_TECHNICAL_CONCEPT",
        "Other technical concept",
        None,
        "A chemistry-specific technical concept that fits no other controlled type.",
    ),
)

CONCEPT_TYPE_BY_CODE = {item.code: item for item in CONCEPT_TYPE_DEFINITIONS}

SCOPE_POLICY_VERSION = "1.0"

IN_SCOPE_RULES = (
    "Include chemical entities, classes, structures, formulas, functional groups, and polymers.",
    "Include materials, mixtures, formulations, coatings, and compositions defined "
    "by chemical or material function.",
    "Include reactions and processes that transform, synthesize, separate, treat, "
    "or manufacture substances or materials.",
    "Include properties, measurements, equipment, and applications only when their "
    "chemical, electrochemical, analytical, or material character is essential.",
)

OUT_OF_SCOPE_RULES = (
    "Exclude generic patent language and generic manufacturing, electrical, mechanical, "
    "anatomical, medical, or product terminology.",
    "Exclude equipment merely present in a chemistry-related document when the equipment "
    "itself is not chemically specialized.",
    "Exclude end products or applications when the phrase carries no chemical or material "
    "meaning by itself.",
    "Exclude vague single words and phrases whose useful meaning exists only in the "
    "surrounding sentence.",
)


def render_type_definitions() -> str:
    return "\n".join(f"- {item.code}: {item.description}" for item in CONCEPT_TYPE_DEFINITIONS)


def render_scope_policy() -> str:
    included = "\n".join(f"- {rule}" for rule in IN_SCOPE_RULES)
    excluded = "\n".join(f"- {rule}" for rule in OUT_OF_SCOPE_RULES)
    return f"IN SCOPE:\n{included}\n\nOUT OF SCOPE:\n{excluded}"
