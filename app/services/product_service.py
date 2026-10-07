from datetime import datetime
from typing import Optional, List
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import Product


class ProductService:
    @staticmethod
    async def create_product(
        session: AsyncSession,
        title: str,
        description: Optional[str] = None,
        price: Optional[str] = None,
        photo_file_id: Optional[str] = None,
        photo_url: Optional[str] = None,
        source: str = "manual",
        status: str = "pending"
    ) -> Product:
        """Створює новий товар у базі даних."""
        product = Product(
            title=title,
            description=description,
            price=price,
            photo_file_id=photo_file_id,
            photo_url=photo_url,
            source=source,
            status=status,
            created_at=datetime.utcnow()
        )
        session.add(product)
        await session.commit()
        await session.refresh(product)
        return product

    @staticmethod
    async def get_product_by_id(session: AsyncSession, product_id: int) -> Optional[Product]:
        """Отримує товар за його ID."""
        result = await session.execute(select(Product).where(Product.id == product_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_pending_products(session: AsyncSession) -> List[Product]:
        """Отримує всі товари, які очікують на публікацію/модерацію."""
        result = await session.execute(
            select(Product)
            .where(Product.status == "pending")
            .order_by(Product.created_at.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def update_product_status(
        session: AsyncSession,
        product_id: int,
        status: str,
        moderated_by: Optional[str] = None
    ) -> Optional[Product]:
        """Оновлює статус товару (published / rejected)."""
        product = await ProductService.get_product_by_id(session, product_id)
        if not product:
            return None

        product.status = status
        product.moderated_by = moderated_by
        if status == "published":
            product.published_at = datetime.utcnow()

        await session.commit()
        await session.refresh(product)
        return product

    @staticmethod
    async def get_latest_products(session: AsyncSession, limit: int = 5) -> List[Product]:
        """Отримує список останніх товарів для адмін-панелі."""
        result = await session.execute(
            select(Product)
            .order_by(desc(Product.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())
