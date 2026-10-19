"""Training submissions produce research artifacts, never deployments."""
import asyncio
from typing import cast

from atlas.models.experiments import ExperimentStore
from atlas.models.providers import TrainingProvider
from atlas.models.registry import ProviderRegistry
from atlas.models.runtime import ProviderRuntime
from atlas.models.schemas import Capability, TrainingJob, TrainingRequest


class TrainingCoordinator:
    def __init__(self, providers: ProviderRegistry, store: ExperimentStore, runtimes: dict[str, ProviderRuntime]) -> None:
        self.providers, self.store, self.runtimes = providers, store, runtimes

    async def submit(self, provider_id: str, request: TrainingRequest) -> TrainingJob:
        provider = cast(TrainingProvider, self.providers.require(provider_id, Capability.TRAIN))
        if request.method == "fine_tune":
            self.providers.require(provider_id, Capability.FINE_TUNE)
        self.store.record(request)
        try:
            job = await self.runtimes[provider_id].call(
                "submit_training", lambda: provider.submit_training(request), retry_safe=False,
                usage=lambda result: result.usage,
            )
            if job.experiment_id != request.experiment_id:
                raise ValueError("Training job does not match experiment")
        except (Exception, asyncio.CancelledError):
            # A submission timeout is ambiguous. Reconcile via the idempotency key;
            # never resubmit automatically and create a second billable job.
            self.store.record_job(TrainingJob(job_id=request.idempotency_key,
                experiment_id=request.experiment_id, state="unknown"))
            raise
        self.store.record_job(job)
        return job
