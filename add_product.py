"""
Скрипт для зручного додавання товарів до клієнтської бази даних client_products.db.

Використання:
    python add_product.py "Назва товару" "Опис товару" "1200 грн" "https://example.com/image.jpg"
або просто запустіть без аргументів для інтерактивного введення:
    python add_product.py
"""
import sys
import sqlite3

DB_FILE = "client_products.db"

def main():
    if len(sys.argv) >= 4:
        title = sys.argv[1]
        description = sys.argv[2]
        price = sys.argv[3]
        photo_url = sys.argv[4] if len(sys.argv) > 4 else None
    else:
        print("=== Додавання товару в клієнтську базу даних ===")
        title = input("Назва товару (title): ").strip()
        if not title:
            print("❌ Назва не може бути порожньою!")
            return
        description = input("Опис товару (description): ").strip()
        price = input("Ціна (price, наприклад: 950 грн): ").strip()
        photo_url = input("Посилання на фото (URL, можна залишити порожнім): ").strip() or None

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            price TEXT,
            photo_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute(
        "INSERT INTO products (title, description, price, photo_url) VALUES (?, ?, ?, ?)",
        (title, description, price, photo_url)
    )
    product_id = cur.lastrowid
    conn.commit()
    conn.close()

    print(f"\n✅ Товар #{product_id} успішно додано до бази {DB_FILE}!")
    print(f"• Назва: {title}")
    print(f"• Опис: {description}")
    print(f"• Ціна: {price}")
    print(f"• Фото: {photo_url or 'Без фото'}")

if __name__ == "__main__":
    main()
