"""troupe's local stage (spec: stages; perform-status-logs design D5).

The actor runs as a process on the host, in the theatre. A process on the host can write any path
and reach any host the person running troupe can, so the local stage enforces no declared effect,
not even a declaration of none: that is a claim it can't check either. It therefore refuses every
actor unless the policy setting allow_unenforced_local_stage is true, and every run it admits
records in lineage that its effects weren't enforced and which source allowed it (decision #3,
option C). The runner's post-run effect check isn't enforcement, and doesn't change this.
"""

from pathlib import Path

from troupe.core.errors import TroupeError
from troupe.core.events.lineage import Allowance
from troupe.core.policy import Policy, env_name
from troupe.core.stages import Admission

NAME = "local"


class LocalStage:
    """Runs the actor on the host, with the theatre's root as its workspace."""

    @property
    def name(self) -> str:
        return NAME

    def workspace(self, theatre: Path) -> Path:
        return theatre

    def admit(self, policy: Policy) -> Admission:
        allowed = policy.allow_unenforced_local_stage
        if not allowed.value:
            variable = env_name(allowed.setting)
            raise TroupeError(
                "stage.effects-unenforced",
                problem="The local stage can't enforce what an actor may touch: it runs as you, "
                "with your files and network. So it runs no actor unless policy allows it, and "
                f"{allowed.setting} is off ({allowed.source}).",
                fix=f"To run actors on the local stage anyway, set {variable}=true. Each run is "
                "then recorded as having its effects unenforced.",
                details={
                    "stage": NAME,
                    "setting": allowed.setting,
                    "source": allowed.source,
                    "variable": variable,
                },
            )
        return Admission(
            name=NAME,
            effects="unenforced",
            allowed_by=Allowance(setting=allowed.setting, source=allowed.source),
        )
