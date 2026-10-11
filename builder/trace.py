"""The builder's trace: start/end time, every model call, what was created on Freya, every test. Plain text + JSON lines."""
import json, pathlib, time


class Trace:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.t0 = time.time()
        self.f = self.path.open("w")
        self.log = self.path.with_suffix(".log").open("w")
        self.event("start", at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))

    def event(self, kind, **data):
        line = {"t": round(time.time() - self.t0, 1), "event": kind, **data}
        self.f.write(json.dumps(line, default=str) + "\n"); self.f.flush()
        text = f"[{line['t']:>6}s] {kind}: " + ", ".join(f"{k}={str(v)[:300]}" for k, v in data.items())
        self.log.write(text + "\n"); self.log.flush()
        print(text[:400], flush=True)

    def model_call(self, model, purpose, usage=None):
        u = {}
        if usage is not None:
            u = {"input_tokens": getattr(usage, "input_tokens", None), "output_tokens": getattr(usage, "output_tokens", None)}
        self.event("model_call", model=model, purpose=purpose, **u)

    def close(self, **data):
        self.event("end", at=time.strftime("%Y-%m-%dT%H:%M:%S%z"), seconds=round(time.time() - self.t0), **data)
        self.f.close(); self.log.close()
