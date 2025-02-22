from __future__ import annotations

import asyncio
import logging
import typing as t
from dataclasses import dataclass, field
from threading import Thread

import numpy as np
from tqdm.auto import tqdm

logger = logging.getLogger(__name__)


class Runner(Thread):
    def __init__(
        self,
        name: str,
        jobs: t.List[t.Tuple[t.Coroutine, str]],
        desc: str,
        keep_progress_bar: bool = True,
        raise_exceptions: bool = True,
    ):
        super().__init__(name=name)
        self.jobs = jobs
        self.desc = desc
        self.keep_progress_bar = keep_progress_bar
        self.raise_exceptions = raise_exceptions
        self.futures = []

        # create task
        self.loop = asyncio.new_event_loop()
        for job in self.jobs:
            coroutine, name = job
            self.futures.append(self.loop.create_task(coroutine, name=name))

    async def _aresults(self) -> t.List[t.Any]:
        results = []
        for future in tqdm(
            asyncio.as_completed(self.futures),
            desc=self.desc,
            total=len(self.futures),
            # whether you want to keep the progress bar after completion
            leave=self.keep_progress_bar,
        ):
            r = (-1, np.nan)
            try:
                r = await future
            except Exception as e:
                if self.raise_exceptions:
                    raise e
            results.append(r)

        return results

    def run(self):
        results = []
        try:
            results = self.loop.run_until_complete(self._aresults())
        except Exception as e:
            if self.raise_exceptions:
                raise e
            else:
                logger.error("Runner in Executor raised an exception", exc_info=True)
                results = None
        finally:
            self.results = results
            [f.cancel() for f in self.futures]
            self.loop.stop()


@dataclass
class Executor:
    desc: str = "Evaluating"
    keep_progress_bar: bool = True
    jobs: t.List[t.Any] = field(default_factory=list, repr=False)
    raise_exceptions: bool = False

    def wrap_callable_with_index(self, callable: t.Callable, counter):
        async def wrapped_callable_async(*args, **kwargs):
            return counter, await callable(*args, **kwargs)

        return wrapped_callable_async

    def submit(
        self, callable: t.Callable, *args, name: t.Optional[str] = None, **kwargs
    ):
        callable_with_index = self.wrap_callable_with_index(callable, len(self.jobs))
        self.jobs.append((callable_with_index(*args, **kwargs), name))

    def results(self) -> t.List[t.Any]:
        executor_job = Runner(
            name="ExecutorRunner",
            jobs=self.jobs,
            desc=self.desc,
            keep_progress_bar=self.keep_progress_bar,
            raise_exceptions=self.raise_exceptions,
        )
        executor_job.start()
        try:
            executor_job.join()
        finally:
            ...

        if executor_job.results is None:
            if self.raise_exceptions:
                raise RuntimeError(
                    "Executor failed to complete. Please check logs above for full info."
                )
            else:
                logger.error("Executor failed to complete. Please check logs above.")
                return []
        sorted_results = sorted(executor_job.results, key=lambda x: x[0])
        return [r[1] for r in sorted_results]
