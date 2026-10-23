"""Build missing licence notices from hash-verified exact-version PyPI source archives."""

import hashlib
import io
import json
import tarfile
from pathlib import Path, PurePosixPath

import httpx

from nevo.api.licences import inventory

OUTPUT = Path(__file__).with_name("generated_notices.json")
UPSTREAM_NOTICES = {
    ("dnspython", "2.9.0"): (
        "https://raw.githubusercontent.com/rthalley/dnspython/v2.9.0/LICENSE",
        "c3ea3ff5654b329c19d3bc5f7481af623c3dded4a6145585499f843ad3d741cd",
    ),
}


def source_notices(name: str, version: str) -> list[dict[str, str]]:
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        metadata = client.get(f"https://pypi.org/pypi/{name}/{version}/json")
        metadata.raise_for_status()
        archive = next(item for item in metadata.json()["urls"] if item["packagetype"] == "sdist")
        if archive["size"] > 25_000_000 or not archive["url"].startswith(
            "https://files.pythonhosted.org/"
        ):
            raise ValueError("Unexpected licence source archive")
        response = client.get(archive["url"])
        response.raise_for_status()
        if hashlib.sha256(response.content).hexdigest() != archive["digests"]["sha256"]:
            raise ValueError("Licence archive checksum mismatch")
    notices = []
    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:*") as files:
        for member in files.getmembers():
            path = PurePosixPath(member.name)
            if (
                not member.isfile()
                or member.size > 2_000_000
                or not path.name.upper().startswith(
                    ("LICENSE", "LICENCE", "COPYING", "COPYRIGHT", "NOTICE")
                )
            ):
                continue
            file = files.extractfile(member)
            if file is not None:
                notices.append(
                    {
                        "name": str(path),
                        "text": file.read().decode("utf-8"),
                        "source": archive["url"],
                        "sha256": archive["digests"]["sha256"],
                    }
                )
    if not notices:
        upstream = UPSTREAM_NOTICES.get((name.lower(), version))
        if upstream is None:
            raise ValueError(f"No licence notices found for {name} {version}")
        response = httpx.get(upstream[0], timeout=30)
        response.raise_for_status()
        if hashlib.sha256(response.content).hexdigest() != upstream[1]:
            raise ValueError("Upstream licence checksum mismatch")
        notices.append(
            {
                "name": "LICENSE (exact upstream release)",
                "text": response.text,
                "source": upstream[0],
                "sha256": upstream[1],
            }
        )
    return notices


def main() -> None:
    data = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    for item in inventory().dependencies:
        if not item.notices:
            data[f"{item.name.lower()}=={item.version}"] = source_notices(item.name, item.version)
    OUTPUT.write_text(json.dumps(data, ensure_ascii=True), encoding="utf-8")
    inventory.cache_clear()
    if any(not item.notices for item in inventory().dependencies):
        raise RuntimeError("Incomplete backend licence inventory")
    print(f"Verified licence notices for {len(inventory().dependencies)} runtime dependencies")


if __name__ == "__main__":
    main()
