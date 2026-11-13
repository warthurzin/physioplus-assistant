import argparse
import statistics
import time

import groq
import httpx
from groq import Groq

from app.core.config import get_settings


def make_client(key: str, ipv4: bool, connect: float, read: float) -> Groq:
    timeout = httpx.Timeout(read, connect=connect)
    http_client = None

    if ipv4:
        http_client = httpx.Client(
            timeout=timeout,
            transport=httpx.HTTPTransport(local_address="0.0.0.0"),
        )

    return Groq(api_key=key, timeout=timeout, max_retries=0, http_client=http_client)


def probe(client: Groq, model: str, count: int, pause: float) -> list[tuple[str, float]]:
    results = []

    for _ in range(count):
        started = time.perf_counter()

        try:
            client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Responda apenas OK"}],
                max_completion_tokens=5,
                temperature=0,
                extra_body={"reasoning_effort": "none"},
            )
            outcome = "ok"
        except groq.APITimeoutError:
            outcome = "timeout"
        except groq.APIConnectionError:
            outcome = "conexao"
        except groq.RateLimitError:
            outcome = "429"
        except groq.APIStatusError as error:
            outcome = f"http{error.status_code}"

        results.append((outcome, time.perf_counter() - started))
        time.sleep(pause)

    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--pause", type=float, default=1.0)
    parser.add_argument("--connect", type=float, default=4.0)
    parser.add_argument("--read", type=float, default=10.0)
    args = parser.parse_args()

    settings = get_settings()
    totals = {"padrao": [], "ipv4": []}

    for index, key in enumerate(settings.groq_key_list):
        for mode in ("padrao", "ipv4"):
            client = make_client(key, mode == "ipv4", args.connect, args.read)
            results = probe(client, settings.groq_model, args.count, args.pause)
            totals[mode].extend(results)

            outcomes = [item[0] for item in results]
            ok_times = [item[1] for item in results if item[0] == "ok"]
            median = f"{statistics.median(ok_times):.2f}s" if ok_times else "n/a"
            print(
                f"chave {index} | {mode:<6} | ok={outcomes.count('ok')}/{len(outcomes)} "
                f"timeout={outcomes.count('timeout')} conexao={outcomes.count('conexao')} "
                f"429={outcomes.count('429')} | mediana={median}"
            )

    print()

    for mode, results in totals.items():
        outcomes = [item[0] for item in results]
        ok_times = sorted(item[1] for item in results if item[0] == "ok")
        slowest = f"{ok_times[-1]:.2f}s" if ok_times else "n/a"
        median = f"{statistics.median(ok_times):.2f}s" if ok_times else "n/a"
        print(
            f"TOTAL {mode:<6} | ok={outcomes.count('ok')}/{len(outcomes)} "
            f"timeout={outcomes.count('timeout')} conexao={outcomes.count('conexao')} "
            f"| mediana={median} pior={slowest}"
        )


if __name__ == "__main__":
    main()