import asyncio
import os
import sys
import json
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.security import encrypt_secret, decrypt_secret, mask_secret, validate_safe_url
from app.core.templating import render_template, render_discord_embed, render_json_template
from app.database import init_db
from app.database.database import async_session_maker
from app.database.models import (
    DataSourceModel,
    PublishChannelModel,
    TemplateModel,
    PublishRuleModel,
    PendingPublicationModel,
    DeliveryLogModel,
    ProcessedRecordModel
)
from app.core.sources.base import DataRecord
from app.core.sources.factory import create_data_source
from app.core.connectors.base import PreparedPost, PublishResult, BasePublisherConnector
from app.core.connectors.factory import create_connector
from app.core.rules.engine import evaluate_filters, prepare_post_content


async def test_all():
    print("--- 1. Testing Security Module ---")
    secret = "SuperSecretDatabasePassword_2026!"
    encrypted = encrypt_secret(secret)
    decrypted = decrypt_secret(encrypted)
    assert decrypted == secret, f"Decryption failed: {decrypted}"
    assert mask_secret(secret) == "Su****6!"
    ok1, _ = validate_safe_url("https://api.telegram.org")
    assert ok1 is True
    ok2, _ = validate_safe_url("http://127.0.0.1/admin")
    assert ok2 is False
    ok3, _ = validate_safe_url("http://localhost:5000")
    assert ok3 is False
    print("✓ Security assertions passed.")

    print("\n--- 2. Testing Templating Module ---")
    sample_data = {
        "title": "Кросівки Nike Air Max",
        "price": 4200,
        "sku": "NK-101",
        "stock": 15
    }
    rendered_text = render_template(
        "Товар: {title}\nЦіна: {price} грн\nОпис: {description|Немає опису}\nНа складі: {stock} шт.",
        sample_data
    )
    assert "Кросівки Nike Air Max" in rendered_text
    assert "4200 грн" in rendered_text
    assert "Немає опису" in rendered_text
    assert "15 шт." in rendered_text

    discord_emb = render_discord_embed(
        title_template="{title}",
        body_template="Ціна: {price} грн | Код: {sku}",
        extra_config={"color": 0x2ECC71},
        data=sample_data
    )
    assert discord_emb["title"] == "Кросівки Nike Air Max"
    assert discord_emb["description"] == "Ціна: 4200 грн | Код: NK-101"
    assert discord_emb["color"] == 3066993

    json_rendered = render_json_template(
        '{"item": "{title}", "cost": {price}, "article": "{sku}"}',
        sample_data
    )
    assert json_rendered["item"] == "Кросівки Nike Air Max"
    assert json_rendered["cost"] == 4200
    assert json_rendered["article"] == "NK-101"
    print("✓ Templating assertions passed.")

    print("\n--- 3. Testing Rules Evaluation & Post Preparation ---")
    filters_test = json.dumps([
        {"field": "price", "op": ">", "value": 1000},
        {"field": "stock", "op": ">=", "value": 10}
    ])
    assert evaluate_filters(sample_data, filters_test) is True

    failing_filters = json.dumps([
        {"field": "price", "op": "<", "value": 1000}
    ])
    assert evaluate_filters(sample_data, failing_filters) is False

    post = prepare_post_content(
        record_data=sample_data,
        template=None,
        rule_name="Test Rule"
    )
    assert "Кросівки Nike Air Max" in post.body
    print("✓ Rule filters & post preparation assertions passed.")

    print("\n--- 4. Testing Database Schema Initialization ---")
    await init_db()
    async with async_session_maker() as session:
        # Create a test DataSource
        ds = DataSourceModel(
            name="Test SQLite Source",
            type="sqlite",
            config_json=encrypt_secret(json.dumps({"database": "sqlite+aiosqlite:///test_source.db"})),
            selected_table="products",
            selected_fields=json.dumps(["id", "title", "price"]),
            pk_field="id",
            change_tracking_mode="full_diff"
        )
        session.add(ds)
        await session.commit()
        await session.refresh(ds)
        assert ds.id is not None
        print(f"✓ Created test DataSource #{ds.id}")

        # Create a test PublishChannel
        ch = PublishChannelModel(
            name="Test Discord Channel",
            type="discord",
            config_json=encrypt_secret(json.dumps({
                "webhook_url": "https://discord.com/api/webhooks/123/abc",
                "use_embed": True
            }))
        )
        session.add(ch)
        await session.commit()
        await session.refresh(ch)
        assert ch.id is not None
        print(f"✓ Created test PublishChannel #{ch.id}")

        # Create a test Template
        tpl = TemplateModel(
            name="General Product Template",
            platform="telegram",
            title_template=None,
            body_template="🔥 <b>{title}</b>\n💰 Ціна: <b>{price} грн</b>"
        )
        session.add(tpl)
        await session.commit()
        await session.refresh(tpl)
        assert tpl.id is not None
        print(f"✓ Created test Template #{tpl.id}")

        # Create a test PublishRule
        rule = PublishRuleModel(
            name="Auto Post Expensive Goods",
            data_source_id=ds.id,
            template_id=tpl.id,
            channel_ids_json=json.dumps([ch.id]),
            trigger_events=json.dumps(["new", "updated"]),
            mode="approval",
            on_update_action="approval",
            check_interval_seconds=60,
            is_active=True
        )
        session.add(rule)
        await session.commit()
        await session.refresh(rule)
        assert rule.id is not None
        print(f"✓ Created test PublishRule #{rule.id}")

        # Clean up test rows
        await session.delete(rule)
        await session.delete(tpl)
        await session.delete(ch)
        await session.delete(ds)
        await session.commit()
        print("✓ Database cleanup complete.")

    print("\n--- 5. Testing Connectors Factory & Base Class ---")
    discord_conn = create_connector("discord", {"webhook_url": "https://discord.com/api/webhooks/123/xyz"})
    assert isinstance(discord_conn, BasePublisherConnector)

    telegram_conn = create_connector("telegram", {"chat_id": "@my_channel"})
    assert isinstance(telegram_conn, BasePublisherConnector)

    http_conn = create_connector("http_api", {"url": "https://example.com/api/hook", "method": "POST"})
    assert isinstance(http_conn, BasePublisherConnector)

    email_conn = create_connector("email", {"smtp_host": "smtp.example.com", "to_email": "admin@example.com"})
    assert isinstance(email_conn, BasePublisherConnector)
    print("✓ All 4 connector types instantiated successfully.")

    print("\n--- 6. Testing DataRecord Hashing ---")
    rec1 = DataRecord(id=101, data={"name": "Shirt", "price": 500})
    rec2 = DataRecord(id=101, data={"name": "Shirt", "price": 500})
    rec3 = DataRecord(id=101, data={"name": "Shirt", "price": 600})
    assert rec1.row_hash == rec2.row_hash
    assert rec1.row_hash != rec3.row_hash
    print("✓ Row hash deduplication logic verified.")

    print("\n==========================================")
    print("🎉 ALL TESTS PASSED SUCCESSFULLY! (6/6)")
    print("==========================================")


if __name__ == "__main__":
    asyncio.run(test_all())
