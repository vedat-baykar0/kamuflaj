#!/usr/bin/env python3
"""
Kamuflaj — Hugging Face Spaces otomatik deploy scripti.
=======================================================

Bu klasordeki tum proje dosyalarini huggingface_hub ile Hugging Face Space'ine
yukler (gerekiyorsa Space'i once kendisi olusturur). Tarayicida surukle-birak
yapmaya gerek yok.

Kurulum (bir kez):
    pip install huggingface_hub

Kullanim:
    python deploy.py                     # token sorar, yukler, build'i bekler
    python deploy.py --space kamuflaj    # Space adini belirt (varsayilan: kamuflaj)
    python deploy.py --dry-run           # hicbir sey yuklemez, ne gonderilecegini listeler
    python deploy.py --sync              # Space'i yerel klasorle birebir eslestirir (fazlalik dosyalari siler)
    python deploy.py --no-wait           # yukleyip cikar, build'i beklemez

Token nereden alinir:
    huggingface.co → sag ust profil → Settings → Access Tokens → "Create new token"
    → Token type: **Write** → kopyala.

Token nasil verilir (ilk bulunani kullanir):
    1) python deploy.py --token hf_xxx
    2) HF_TOKEN ortam degiskeni
    3) proje klasorundeki .hf_token dosyasi (script ilk calismada kaydetmeyi teklif eder)
    4) ekranda sorar (yazarken gorunmez)
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
import time
from getpass import getpass
from pathlib import Path

# Windows konsolunda Turkce/isaret karakterleri patlatmasin
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT_DIR = Path(__file__).resolve().parent
TOKEN_FILE = PROJECT_DIR / ".hf_token"
DEFAULT_SPACE = "kamuflaj"
BUILD_TIMEOUT = 900  # saniye

# Space'te mutlaka bulunmasi gereken dosyalar
REQUIRED_FILES = [
    "main.py",
    "words.py",
    "requirements.txt",
    "Dockerfile",
    "README.md",
    "templates/index.html",
    "static/app.js",
]

# Yuklenmeyecekler (.venv 36 MB'lik gereksiz test klasoru, token dosyasi gizli kalmali)
IGNORE_PATTERNS = [
    ".venv/*", "venv/*", "env/*",
    "__pycache__/*", "*/__pycache__/*", "*.pyc", "*.pyo",
    ".git/*", ".github/*", ".idea/*", ".vscode/*",
    "*.log", "*.tmp", ".DS_Store", "Thumbs.db",
    ".hf_token", ".env", "*.sqlite3",
    "deploy.py",  # deploy scripti sunucuda gereksiz
]


# ---------------------------------------------------------------- yardimcilar

def say(msg: str) -> None:
    print(msg, flush=True)


def ok(msg: str) -> None:
    print(f"[OK]   {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[!]    {msg}", flush=True)


def die(msg: str, hint: str = "") -> "None":
    print(f"\n[HATA] {msg}", flush=True)
    if hint:
        print(f"       -> {hint}", flush=True)
    sys.exit(1)


def ensure_hub():
    """huggingface_hub kurulu degilse izin isteyip kurar."""
    try:
        import huggingface_hub  # noqa: F401
    except ImportError:
        warn("huggingface_hub kurulu degil.")
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "huggingface_hub"]
        answer = input("       Simdi kurulsun mu? [E/h] ").strip().lower()
        if answer not in ("", "e", "evet", "y", "yes"):
            die("huggingface_hub gerekli.", " ".join(cmd))
        if subprocess.call(cmd) != 0:
            die("Kurulum basarisiz oldu.", " ".join(cmd) + " komutunu elle dene.")
        say("")
    from huggingface_hub import HfApi  # noqa: WPS433
    return HfApi


def ignored(rel_path: str) -> bool:
    return any(fnmatch.fnmatch(rel_path, pattern) for pattern in IGNORE_PATTERNS)


def collect_files() -> list[str]:
    """Yuklenecek dosyalarin listesi (huggingface_hub ile ayni filtreleme mantigi)."""
    found: list[str] = []
    for path in sorted(PROJECT_DIR.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(PROJECT_DIR).as_posix()
        if not ignored(rel):
            found.append(rel)
    return found


def check_project(files: list[str]) -> None:
    """Deploy oncesi saglik kontrolu: eksik dosya ve HF ayar blogu."""
    missing = [name for name in REQUIRED_FILES if name not in files]
    if missing:
        die(
            "Su dosyalar bulunamadi: " + ", ".join(missing),
            "Scripti proje klasorunun icinden calistirdigindan emin ol: " + str(PROJECT_DIR),
        )

    readme = (PROJECT_DIR / "README.md").read_text(encoding="utf-8", errors="replace")
    head = readme.lstrip()
    problems = []
    if not head.startswith("---"):
        problems.append("README.md en ustte YAML ayar blogu (---) ile baslamiyor")
    if "sdk: docker" not in readme:
        problems.append("README.md icinde 'sdk: docker' yok")
    if "app_port: 7860" not in readme:
        problems.append("README.md icinde 'app_port: 7860' yok")
    if problems:
        die(
            "Hugging Face ayar blogu eksik: " + "; ".join(problems),
            "README.md'nin ilk satirlari sdk: docker ve app_port: 7860 icermeli.",
        )

    dockerfile = (PROJECT_DIR / "Dockerfile").read_text(encoding="utf-8", errors="replace")
    if "7860" not in dockerfile:
        warn("Dockerfile icinde 7860 portu gorunmuyor; HF Spaces 7860 bekler.")

    total_mb = sum((PROJECT_DIR / f).stat().st_size for f in files) / (1024 * 1024)
    ok(f"{len(files)} dosya hazir ({total_mb:.2f} MB), zorunlu dosyalarin hepsi yerinde.")


def resolve_token(cli_token: str | None, dry_run: bool) -> str:
    if cli_token:
        return cli_token.strip()
    for env_key in ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGINGFACEHUB_API_TOKEN"):
        value = os.environ.get(env_key, "").strip()
        if value:
            ok(f"Token {env_key} ortam degiskeninden alindi.")
            return value
    if TOKEN_FILE.exists():
        value = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if value:
            ok(f"Token {TOKEN_FILE.name} dosyasindan alindi.")
            return value
    if dry_run:
        return ""

    say("")
    say("Hugging Face 'Write' yetkili token'ini gir (yazarken ekranda gorunmez).")
    say("Token almak icin: huggingface.co → Settings → Access Tokens → Create new token → Write")
    token = getpass("Token: ").strip()
    if not token:
        die("Token girilmedi.")
    answer = input(f"Bu token {TOKEN_FILE.name} dosyasina kaydedilsin mi (bir daha sorulmaz)? [E/h] ").strip().lower()
    if answer in ("", "e", "evet", "y", "yes"):
        TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
        ok(f"{TOKEN_FILE.name} kaydedildi (.gitignore ve .dockerignore icinde, yuklenmez).")
    return token


def subdomain(owner: str, space: str) -> str:
    """HF alt alan adi kurali: harf/rakam disindaki her sey tireye doner."""
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", f"{owner}-{space}".lower()).strip("-")
    return f"https://{slug}.hf.space"


def wait_for_build(api, repo_id: str, space_url: str) -> None:
    """Build bitene kadar durumu izler."""
    say("")
    say("Build izleniyor (ortalama 2-4 dakika, Ctrl+C ile cikabilirsin)...")
    good = {"RUNNING", "RUNNING_APP_STARTING"}
    bad = {"BUILD_ERROR", "CONFIG_ERROR", "RUNTIME_ERROR", "NO_APP_FILE"}
    started = time.time()
    last_stage = ""
    while time.time() - started < BUILD_TIMEOUT:
        try:
            stage = str(api.get_space_runtime(repo_id).stage or "").upper()
        except Exception as exc:  # gecici ag/API hatasi
            stage = ""
            warn(f"Durum okunamadi ({type(exc).__name__}), tekrar denenecek.")
        if stage and stage != last_stage:
            say(f"       durum: {stage}")
            last_stage = stage
        if stage in good:
            ok("Space calisiyor!")
            return
        if stage in bad:
            die(
                f"Space build/calisma hatasi: {stage}",
                f"Loglari gor: https://huggingface.co/spaces/{repo_id}?logs=build",
            )
        if stage in {"PAUSED", "STOPPED", "SLEEPING"}:
            warn(f"Space su an {stage}. Linke girince uyanir: {space_url}")
            return
        time.sleep(5)
    warn("Build beklenenden uzun surdu. Durumu su adresten izleyebilirsin:")
    say(f"       https://huggingface.co/spaces/{repo_id}")


# ---------------------------------------------------------------------- akis

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Kamuflaj projesini Hugging Face Spaces'e yukler.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--token", help="HF 'Write' token (yoksa ortam degiskeni/dosya/soru)")
    parser.add_argument("--space", default=DEFAULT_SPACE, help=f"Space adi (varsayilan: {DEFAULT_SPACE})")
    parser.add_argument("--owner", help="Hesap/organizasyon adi (varsayilan: token sahibi)")
    parser.add_argument("--private", action="store_true", help="Space'i gizli olustur (oynamak icin giris gerekir)")
    parser.add_argument("--message", default="Kamuflaj deploy", help="Commit mesaji")
    parser.add_argument("--sync", action="store_true",
                        help="Space'i yerel klasorle birebir esle: uzaktaki fazla dosyalari sil")
    parser.add_argument("--no-wait", action="store_true", help="Build'i bekleme, yukleyip cik")
    parser.add_argument("--dry-run", action="store_true", help="Hicbir sey yukleme, sadece ne gonderilecegini goster")
    args = parser.parse_args()

    say("=" * 64)
    say("  Kamuflaj -> Hugging Face Spaces deploy")
    say("=" * 64)
    say(f"Proje klasoru: {PROJECT_DIR}")

    files = collect_files()
    check_project(files)

    if args.dry_run:
        say("")
        say("Yuklenecek dosyalar:")
        for rel in files:
            size_kb = (PROJECT_DIR / rel).stat().st_size / 1024
            say(f"       {rel:<28} {size_kb:>8.1f} KB")
        skipped = [
            p.relative_to(PROJECT_DIR).as_posix()
            for p in PROJECT_DIR.iterdir()
            if ignored(p.relative_to(PROJECT_DIR).as_posix() + ("/*" if p.is_dir() else ""))
            or ignored(p.relative_to(PROJECT_DIR).as_posix())
        ]
        if skipped:
            say("")
            say("Atlanacaklar: " + ", ".join(sorted(skipped)))
        owner = args.owner or "<kullanici-adin>"
        say("")
        say(f"Hedef Space : {owner}/{args.space}")
        say(f"Canli adres : {subdomain(owner, args.space)}")
        say("")
        ok("Dry-run tamam. Gercekten yuklemek icin --dry-run olmadan calistir.")
        return

    HfApi = ensure_hub()
    token = resolve_token(args.token, dry_run=False)
    api = HfApi(token=token)

    # 1) Token dogrulama
    try:
        me = api.whoami()
    except Exception as exc:
        die(
            f"Token dogrulanamadi ({type(exc).__name__}).",
            "Token'i huggingface.co → Settings → Access Tokens'tan 'Write' tipinde yeniden olustur.",
        )
    owner = args.owner or me.get("name")
    if not owner:
        die("Hesap adi belirlenemedi.", "--owner ile elle yaz.")
    role = ((me.get("auth") or {}).get("accessToken") or {}).get("role")
    if role and role != "write":
        die(f"Bu token '{role}' yetkili, yukleme yapamaz.", "'Write' tipinde yeni bir token olustur.")
    ok(f"Giris yapildi: {owner}" + (f" (token yetkisi: {role})" if role else ""))

    repo_id = f"{owner}/{args.space}"
    space_url = subdomain(owner, args.space)

    # 2) Space yoksa olustur
    try:
        api.create_repo(
            repo_id=repo_id,
            repo_type="space",
            space_sdk="docker",
            private=args.private,
            exist_ok=True,
        )
        ok(f"Space hazir: {repo_id}")
    except Exception as exc:
        die(f"Space olusturulamadi: {exc}", "Space adi baska biri tarafindan kullaniliyor olabilir, --space ile degistir.")

    # 3) Dosyalari yukle
    say("")
    say(f"{len(files)} dosya yukleniyor...")
    try:
        api.upload_folder(
            folder_path=str(PROJECT_DIR),
            repo_id=repo_id,
            repo_type="space",
            commit_message=args.message,
            ignore_patterns=IGNORE_PATTERNS,
            delete_patterns=["*"] if args.sync else None,
        )
    except Exception as exc:
        die(f"Yukleme basarisiz: {exc}", "Internet baglantisini ve token yetkisini kontrol et.")
    ok("Dosyalar yuklendi, Hugging Face Docker imajini derlemeye basladi.")

    # 4) Build'i izle
    if not args.no_wait:
        wait_for_build(api, repo_id, space_url)

    say("")
    say("=" * 64)
    say("  HAZIR")
    say("=" * 64)
    say(f"  Arkadaslarina gonderecegin link : {space_url}")
    say(f"  Yonetim / loglar               : https://huggingface.co/spaces/{repo_id}")
    say("")
    say("  Hic uykuya gecmemesi icin cron-job.org'da 10 dakikalik bir is kur:")
    say(f"      {space_url}/healthz")
    say("")
    say("  Sonraki guncellemeler: dosyayi degistir, 'python deploy.py' calistir.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        say("\nIptal edildi.")
        sys.exit(130)
