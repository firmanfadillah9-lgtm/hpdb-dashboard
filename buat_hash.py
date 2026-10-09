r"""
buat_hash.py
------------
Bikin blok [credentials] untuk Streamlit Secrets.

Jalankan:
    C:\Users\RYZEN\AppData\Local\Programs\Python\Python312\python.exe C:\homepass\buat_hash.py

Password diketik saat diminta (tidak tampil di layar, tidak tersimpan di file).
Hasilnya blok TOML siap tempel ke: Manage app -> Settings -> Secrets
"""
import hashlib
import getpass

ALGO = "sha256"   # ganti ke "md5"/"sha512" kalau dashboard.py pakai yang lain


def hash_pw(pw: str) -> str:
    return hashlib.new(ALGO, pw.encode("utf-8")).hexdigest()


def main():
    print("=" * 66)
    print("  BUAT BLOK [credentials] UNTUK STREAMLIT SECRETS")
    print(f"  Algoritma: {ALGO}")
    print("=" * 66)
    print("  Enter kosong pada username = selesai\n")

    users = []
    while True:
        u = input("Username    : ").strip()
        if not u:
            break
        nama = input("Nama tampil : ").strip() or u
        role = input("Role [super_admin/viewer] (default viewer): ").strip() or "viewer"

        pw1 = getpass.getpass("Password    : ")
        pw2 = getpass.getpass("Ulangi      : ")
        if pw1 != pw2:
            print("  !! Password tidak sama, user ini dilewati.\n")
            continue
        if len(pw1) < 6:
            print("  !! Minimal 6 karakter, user ini dilewati.\n")
            continue

        users.append((u, nama, role, hash_pw(pw1)))
        print(f"  OK user '{u}' ditambahkan.\n")

    if not users:
        print("Tidak ada user dibuat.")
        return

    print("\n" + "=" * 66)
    print("  COPY MULAI DARI BARIS DI BAWAH INI")
    print("=" * 66 + "\n")
    for u, nama, role, h in users:
        print(f'[credentials.{u}]')
        print(f'password_hash = "{h}"')
        print(f'role = "{role}"')
        print(f'name = "{nama}"')
        print()
    print("=" * 66)
    print("  Tempel ke: Manage app -> Settings -> Secrets")
    print("  Taruh DI BAWAH secret yang sudah ada (GITHUB_TOKEN dst),")
    print("  karena blok [tabel] di TOML harus berada setelah key biasa.")
    print("=" * 66)


if __name__ == "__main__":
    main()
