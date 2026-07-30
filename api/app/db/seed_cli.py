from app.db.seed.catalogs import seed_catalogs
from app.db.session import SessionLocal


def main() -> None:
    with SessionLocal.begin() as session:
        result = seed_catalogs(session)
    print(f"Catalog seed completed: inserted={result.inserted} existing={result.existing}")


if __name__ == "__main__":
    main()
