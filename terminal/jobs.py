"""One background simulation at a time, with cancellable progress and bounded history."""

from collections import OrderedDict
from secrets import token_hex
from threading import Lock, Thread

from .market import MarketUnavailable


class Cancelled(Exception):
    pass


class Simulations:
    def __init__(self, slot, logger):
        self.slot = slot
        self.logger = logger
        self.guard = Lock()
        self.jobs = OrderedDict()
        self.active = None

    def start(self, compute, save):
        if not self.slot.acquire(blocking=False):
            return None
        job_id = token_hex(16)
        with self.guard:
            self.jobs[job_id] = {"status": "loading", "value": 0, "total": 0}
            self.active = job_id
            if len(self.jobs) > 8:
                self.jobs.popitem(last=False)
        try:
            Thread(target=self._worker, args=(job_id, compute, save), daemon=True).start()
        except Exception:
            with self.guard:
                del self.jobs[job_id]
                self.active = None
                self.slot.release()
            raise
        return job_id

    def status(self, job_id):
        with self.guard:
            job = self.jobs.get(job_id)
            return dict(job) if job else None

    def cancel(self, job_id):
        with self.guard:
            if job_id != self.active:
                return False
            job = self.jobs[job_id]
            if job["status"] not in ("loading", "running", "cancelling"):
                return False
            job["status"] = "cancelling"
            return True

    def _worker(self, job_id, compute, save):
        job = self.jobs[job_id]

        def progress(value, total):
            with self.guard:
                if job["status"] == "cancelling":
                    raise Cancelled()
                job.update(status="running", value=value, total=total)

        final = {"status": "error", "error": "No se pudo completar la simulación."}
        try:
            result = compute(progress)
            with self.guard:
                if job["status"] == "cancelling":
                    raise Cancelled()
                job["status"] = "saving"
            stored = save(result)
            final = {"status": "done", "run_id": stored["id"]}
        except Cancelled:
            final = {"status": "cancelled"}
        except (ValueError, MarketUnavailable) as error:
            final = {"status": "error", "error": str(error)}
        except Exception:
            self.logger.exception("Simulation failed")
        finally:
            with self.guard:
                if job["status"] == "cancelling":
                    final = {"status": "cancelled"}
                job.update(final)
                self.active = None
                self.slot.release()
