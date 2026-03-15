"""
SafetyGuard — risk analysis and discussion layer for ha-mcp-plus.

Every high-risk operation goes through this module BEFORE execution.
The tool returns a detailed plan + risk analysis and waits for the user
to either approve, discuss, or improve the plan.

Risk levels:
    LOW    — reversible, no system impact (e.g. read operations)
    MEDIUM — reversible with effort (e.g. dashboard changes, automation create)
    HIGH   — hard to reverse, may break system (e.g. configuration.yaml write)
    CRITICAL — could make system unbootable (e.g. HA restart, addon stop)

Workflow:
    1. Tool called with execute=False (default)
       → Returns plan + risk analysis + discussion prompt
       → System waits — NOTHING is executed
    2. User discusses, asks questions, requests changes
    3. User explicitly calls tool again with execute=True
       → Action is executed
       → Result returned with rollback info
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from enum import Enum
import logging

log = logging.getLogger("ha-mcp-plus.safety")


class RiskLevel(str, Enum):
    LOW      = "LOW"
    MEDIUM   = "MEDIUM"
    HIGH     = "HIGH"
    CRITICAL = "CRITICAL"


RISK_COLORS = {
    RiskLevel.LOW:      "🟢",
    RiskLevel.MEDIUM:   "🟡",
    RiskLevel.HIGH:     "🟠",
    RiskLevel.CRITICAL: "🔴",
}


@dataclass
class RiskFactor:
    description: str
    mitigation: str
    probability: str   # "laag", "matig", "hoog"


@dataclass
class SafetyPlan:
    """
    A safety plan describes WHAT will happen, WHY it might go wrong,
    and HOW to recover — before anything is executed.
    """
    operation_name: str
    risk_level: RiskLevel

    # What exactly will happen (in plain Dutch)
    what_will_happen: list[str]

    # What files/entities/flows will be affected
    affected_resources: list[str]

    # Risk factors with mitigations
    risk_factors: list[RiskFactor]

    # How to undo this if it goes wrong
    rollback_instructions: list[str]

    # Estimated recovery time if something breaks
    recovery_time_estimate: str

    # Probability that system stops working (0-100)
    system_failure_probability: int

    # Optional: what alternatives exist
    alternatives: list[str] = field(default_factory=list)

    def render(self) -> str:
        """Render the safety plan as a human-readable string."""
        icon = RISK_COLORS[self.risk_level]
        lines = [
            f"",
            f"## {icon} Veiligheidsanalyse — {self.operation_name}",
            f"",
            f"**Risico niveau:** {icon} {self.risk_level.value}",
            f"**Kans dat systeem niet meer werkt:** {self.system_failure_probability}%",
            f"**Hersteltijd als het misgaat:** {self.recovery_time_estimate}",
            f"",
            f"### Wat ga ik doen?",
        ]
        for i, step in enumerate(self.what_will_happen, 1):
            lines.append(f"{i}. {step}")

        lines += ["", "### Welke resources worden aangeraakt?"]
        for r in self.affected_resources:
            lines.append(f"- `{r}`")

        lines += ["", "### Risicofactoren"]
        for rf in self.risk_factors:
            lines += [
                f"",
                f"**{rf.description}**",
                f"- Kans: {rf.probability}",
                f"- Beperking: {rf.mitigation}",
            ]

        lines += ["", "### Als het misgaat — hoe herstel je?"]
        for i, step in enumerate(self.rollback_instructions, 1):
            lines.append(f"{i}. {step}")

        if self.alternatives:
            lines += ["", "### Alternatieven"]
            for alt in self.alternatives:
                lines.append(f"- {alt}")

        lines += [
            "",
            "---",
            "",
            "💬 **Wil je iets aanpassen of bespreken?** Reageer dan nu — ik voer nog niets uit.",
            "✅ **Klaar om door te gaan?** Zeg dan expliciet dat je wilt dat ik het uitvoer.",
            "",
        ]
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Pre-built safety plans for known operations
# ─────────────────────────────────────────────────────────────────────────────

def plan_append_config_yaml(yaml_block: str, comment: str, config_path: str) -> SafetyPlan:
    lines = yaml_block.strip().splitlines()
    return SafetyPlan(
        operation_name="Schrijven naar configuration.yaml",
        risk_level=RiskLevel.HIGH,
        what_will_happen=[
            f"Een backup maken van `configuration.yaml` met timestamp",
            f"De volgende {len(lines)} regels YAML toevoegen aan het einde van `configuration.yaml`:",
            f"```yaml\n{yaml_block[:300]}{'...' if len(yaml_block) > 300 else ''}\n```",
            f"HA herladen zodat de nieuwe configuratie actief wordt",
        ],
        affected_resources=[
            f"{config_path}/configuration.yaml",
            f"{config_path}/configuration.yaml.bak.[timestamp]",
        ],
        risk_factors=[
            RiskFactor(
                description="Ongeldige YAML syntax",
                mitigation="Ik valideer de YAML vóór schrijven — bij een parse-fout wordt er niets geschreven",
                probability="laag (syntax wordt gecontroleerd)",
            ),
            RiskFactor(
                description="Conflict met bestaande configuratie",
                mitigation="Ik voeg toe aan het einde — bestaande config blijft intact",
                probability="matig als er al een sectie met dezelfde naam bestaat",
            ),
            RiskFactor(
                description="HA start niet meer op na herlaad",
                mitigation="Backup is beschikbaar — de backup terugzetten duurt < 1 minuut",
                probability="laag als de YAML semantisch correct is",
            ),
        ],
        rollback_instructions=[
            f"Ga naar Studio Code Server in HA",
            f"Open `{config_path}/configuration.yaml.bak.[timestamp]`",
            f"Kopieer de inhoud terug naar `configuration.yaml`",
            f"Herstart HA via Instellingen → Systeem → Herstarten",
        ],
        recovery_time_estimate="2–5 minuten",
        system_failure_probability=8,
        alternatives=[
            "Ik kan de YAML ook alleen laten zien zonder te schrijven, zodat je hem handmatig kunt plakken",
            "Ik kan eerst de huidige configuration.yaml laten zien om te checken of er conflicten zijn",
        ],
    )


def plan_nodered_deploy_flow(flow_label: str, flow_summary: str, is_new: bool) -> SafetyPlan:
    action = "aanmaken" if is_new else "overschrijven"
    return SafetyPlan(
        operation_name=f"Node-RED flow {action}: '{flow_label}'",
        risk_level=RiskLevel.HIGH,
        what_will_happen=[
            f"De flow '{flow_label}' {action} in Node-RED",
            f"Flow inhoud: {flow_summary}",
            f"Node-RED deploy uitvoeren zodat de flow direct actief wordt",
        ],
        affected_resources=[
            f"Node-RED flow: {flow_label}",
            "Node-RED flows.json (alle flows worden opgeslagen)",
        ],
        risk_factors=[
            RiskFactor(
                description="Flow heeft fouten die HA diensten verkeerd aanroepen",
                mitigation="Ik laat de volledige flow JSON zien vóór deployment",
                probability="matig — afhankelijk van complexiteit",
            ),
            RiskFactor(
                description="Bestaande flow wordt overschreven",
                mitigation="Ik haal de huidige flow op en sla hem op vóór overschrijven",
                probability="van toepassing als flow_label al bestaat",
            ) if not is_new else RiskFactor(
                description="Nieuwe flow interfereert met bestaande automations",
                mitigation="Controleer of er overlap is met bestaande triggers",
                probability="laag bij unieke trigger entities",
            ),
        ],
        rollback_instructions=[
            "In Node-RED: ga naar Menu → Import → plak de oude flow JSON",
            "Of: verwijder de nieuwe flow via nodered_delete_flow(flow_id=...)",
            "Node-RED bewaart geen automatische backups — sla de huidige flows op vóór deployment",
        ],
        recovery_time_estimate="1–3 minuten",
        system_failure_probability=3,
        alternatives=[
            "Ik kan de flow JSON alleen genereren en tonen, zodat jij hem handmatig importeert in Node-RED",
            "Ik kan eerst alle bestaande flows tonen om te checken op conflicten",
            "We kunnen de flow eerst in disabled-modus deployen en pas later activeren",
        ],
    )


def plan_supervisor_restart_ha() -> SafetyPlan:
    return SafetyPlan(
        operation_name="Home Assistant herstarten",
        risk_level=RiskLevel.CRITICAL,
        what_will_happen=[
            "HA Core stoppen",
            "Alle actieve automations en scripts worden onderbroken",
            "HA Core opnieuw opstarten — duurt typisch 30–90 seconden",
            "Alle verbindingen (inclusief deze MCP sessie) worden verbroken",
        ],
        affected_resources=[
            "Home Assistant Core process",
            "Alle actieve automations en scripts",
            "Alle integraties en apparaatverbindingen",
        ],
        risk_factors=[
            RiskFactor(
                description="HA start niet meer op door config-fout",
                mitigation="Voer altijd een config check uit vóór herstart",
                probability="laag als config recent gevalideerd is",
            ),
            RiskFactor(
                description="Tijdelijk geen bediening van apparaten",
                mitigation="Herstart duurt typisch < 2 minuten",
                probability="zeker — dit is inherent aan herstart",
            ),
        ],
        rollback_instructions=[
            "Als HA niet opstart: ga naar de HA host via SSH",
            "Controleer de logs: `journalctl -u homeassistant -n 50`",
            "Herstel de laatste backup via de Supervisor UI",
        ],
        recovery_time_estimate="30 seconden – 2 minuten (normaal), 5–15 minuten (bij opstartfout)",
        system_failure_probability=2,
        alternatives=[
            "Gebruik supervisor_reload_core() als je alleen YAML wijzigingen wilt activeren — geen volledige herstart",
            "Gebruik ha_check_config() eerst om de configuratie te valideren",
        ],
    )


def plan_addon_stop(slug: str, name: str) -> SafetyPlan:
    return SafetyPlan(
        operation_name=f"Add-on stoppen: {name} ({slug})",
        risk_level=RiskLevel.MEDIUM,
        what_will_happen=[
            f"De add-on '{name}' stoppen",
            f"Alle verbindingen met '{name}' worden verbroken",
        ],
        affected_resources=[f"Add-on: {slug}"],
        risk_factors=[
            RiskFactor(
                description=f"Diensten die afhankelijk zijn van {name} stoppen met werken",
                mitigation="Controleer welke automations en integraties deze add-on gebruiken",
                probability="matig — afhankelijk van hoe de add-on gebruikt wordt",
            ),
        ],
        rollback_instructions=[
            f"Start de add-on opnieuw via supervisor_addon_start(slug='{slug}')",
            "Of via HA UI: Instellingen → Add-ons → {name} → Starten",
        ],
        recovery_time_estimate="< 1 minuut",
        system_failure_probability=1,
        alternatives=[
            f"Gebruik supervisor_addon_restart(slug='{slug}') als je een herstart wilt",
        ],
    )


def plan_write_file(relative_path: str, content_preview: str, overwrite: bool) -> SafetyPlan:
    risk = RiskLevel.HIGH if overwrite else RiskLevel.MEDIUM
    return SafetyPlan(
        operation_name=f"Bestand {'overschrijven' if overwrite else 'aanmaken'}: {relative_path}",
        risk_level=risk,
        what_will_happen=[
            f"Het bestand `/config/{relative_path}` {'overschrijven' if overwrite else 'aanmaken'}",
            f"Inhoud (eerste 200 tekens): `{content_preview[:200]}`",
        ],
        affected_resources=[f"/config/{relative_path}"],
        risk_factors=[
            RiskFactor(
                description="Bestaand bestand verloren als overwrite=True",
                mitigation="Ik maak eerst een backup met timestamp",
                probability="van toepassing" if overwrite else "niet van toepassing",
            ),
        ],
        rollback_instructions=[
            "Backup staat op /config/{relative_path}.bak.[timestamp]",
            "Kopieer de backup terug via Studio Code Server",
        ],
        recovery_time_estimate="1–2 minuten",
        system_failure_probability=1 if not overwrite else 5,
        alternatives=[
            "Ik kan de bestandsinhoud alleen tonen zodat jij hem handmatig aanmaakt",
        ],
    )
