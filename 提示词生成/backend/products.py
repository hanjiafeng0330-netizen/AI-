import time
import uuid

from .config import PRODUCTS_DIR
from .models import Product, ProductCreateRequest


def list_products(grade: str | None = None) -> list[Product]:
    products = [
        Product.model_validate_json(path.read_text(encoding="utf-8"))
        for path in PRODUCTS_DIR.glob("*.json")
    ]
    if grade:
        products = [p for p in products if p.grade == grade]
    products.sort(key=lambda p: p.created_at, reverse=True)
    return products


def get_product(product_id: str) -> Product | None:
    path = PRODUCTS_DIR / f"{product_id}.json"
    if not path.exists():
        return None
    return Product.model_validate_json(path.read_text(encoding="utf-8"))


def create_product(req: ProductCreateRequest) -> Product:
    product = Product(id=uuid.uuid4().hex[:12], created_at=time.time(), **req.model_dump())
    _save(product)
    return product


def update_product(product_id: str, req: ProductCreateRequest) -> Product | None:
    existing = get_product(product_id)
    if existing is None:
        return None
    updated = existing.model_copy(update=req.model_dump())
    _save(updated)
    return updated


def delete_product(product_id: str) -> bool:
    path = PRODUCTS_DIR / f"{product_id}.json"
    if not path.exists():
        return False
    path.unlink()
    return True


def _save(product: Product) -> None:
    path = PRODUCTS_DIR / f"{product.id}.json"
    path.write_text(product.model_dump_json(indent=2), encoding="utf-8")
