"""Registry navigation uses only isolated synthetic test records and verified seed reads."""

from __future__ import annotations

from app.assets.service import category_navigation
from app.models import AssetCategory, Machine
from sqlalchemy import event, select


def _categories(session_factory):
    with session_factory() as db:
        paint = AssetCategory(
            code="QA_PAINT", name_bg="Бояджийски машини", name_en="Paint machines",
            name_ru="Окрасочные машины", capabilities=[], is_active=True,
        )
        robot = AssetCategory(
            code="QA_ROBOT", name_bg="Роботи", name_en="Robots",
            name_ru="Роботы", capabilities=[], is_active=True,
        )
        inactive = AssetCategory(
            code="QA_INACTIVE", name_bg="Неактивна категория", capabilities=[], is_active=False,
        )
        empty_inactive = AssetCategory(
            code="QA_EMPTY_INACTIVE", name_bg="Празна неактивна", capabilities=[], is_active=False,
        )
        db.add_all([paint, robot, inactive, empty_inactive])
        db.flush()
        for index in range(3):
            db.add(Machine(
                inventory_number=f"QA-PAINT-{index}", name=f"QA paint {index}",
                brand="QA", category=paint.code, category_id=paint.id,
                is_active=index != 0,
            ))
        db.add(Machine(
            inventory_number="QA-INACTIVE-1", name="QA inactive", brand="QA",
            category=inactive.code, category_id=inactive.id,
        ))
        db.commit()
        return paint.id, robot.id, inactive.id, empty_inactive.id


def test_registry_navigation_counts_filtering_lifecycle_and_permissions(
    client, auth_headers, viewer_headers, session_factory, machine_ids,
):
    assert len(machine_ids) == 19
    paint_id, robot_id, inactive_id, empty_inactive_id = _categories(session_factory)
    response = client.get("/api/machines/category-navigation", headers=viewer_headers)
    assert response.status_code == 200
    rows = response.json()
    assert rows == sorted(rows, key=lambda row: (row["name_bg"].casefold(), row["code"], row["id"]))
    by_code = {row["code"]: row for row in rows}
    assert by_code["HPWJ"]["asset_count"] == 19
    assert by_code["HPWJ"]["has_pressure"] is True
    assert by_code["QA_PAINT"]["asset_count"] == 3
    assert by_code["QA_ROBOT"]["asset_count"] == 0
    assert by_code["QA_INACTIVE"]["asset_count"] == 1
    assert by_code["QA_INACTIVE"]["is_active"] is False
    assert "QA_EMPTY_INACTIVE" not in by_code
    assert set(by_code["QA_PAINT"]) == {
        "id", "code", "name_bg", "name_en", "name_ru", "is_active",
        "asset_count", "has_pressure",
    }
    assert client.get("/api/machines/category-navigation").status_code == 401
    assert client.get("/api/categories", headers=viewer_headers).status_code == 403

    for category_id, expected in ((paint_id, 3), (robot_id, 0), (inactive_id, 1)):
        listing = client.get(f"/api/machines?category_id={category_id}", headers=auth_headers)
        assert listing.status_code == 200
        assert len(listing.json()) == expected
        assert all(row["category_id"] == category_id for row in listing.json())
    assert len(client.get("/api/machines", headers=auth_headers).json()) == 23
    assert client.get("/api/machines?category_id=999999", headers=auth_headers).status_code == 404
    assert client.get("/api/machines?category_id=0", headers=auth_headers).status_code == 422

    observer = client.get(f"/api/machines?category_id={paint_id}", headers=viewer_headers)
    assert observer.status_code == 200
    assert len(observer.json()) == 3
    assert all(set(row) == {
        "id", "inventory_number", "name", "category", "category_id", "brand",
        "model", "status", "is_active", "location",
    } for row in observer.json())
    assert client.post("/api/machines", headers=auth_headers, json={
        "inventory_number": "QA-BLOCKED-INACTIVE", "name": "QA", "brand": "QA",
        "category_id": inactive_id,
    }).status_code == 422
    existing_inactive = client.get(
        f"/api/machines?category_id={inactive_id}", headers=auth_headers,
    ).json()[0]
    assert client.patch(
        f"/api/machines/{existing_inactive['id']}", headers=auth_headers,
        json={"notes": "QA edit"},
    ).status_code == 200
    assert client.patch(
        f"/api/machines/{existing_inactive['id']}", headers=auth_headers,
        json={"category_id": inactive_id},
    ).status_code == 200
    paint_asset = client.get(f"/api/machines?category_id={paint_id}", headers=auth_headers).json()[0]
    assert client.patch(
        f"/api/machines/{paint_asset['id']}", headers=auth_headers,
        json={"category_id": inactive_id},
    ).status_code == 422
    with session_factory() as db:
        assert len(db.scalars(select(Machine).where(Machine.id.in_(machine_ids.values()))).all()) == 19
        assert db.get(AssetCategory, empty_inactive_id).is_active is False


def test_navigation_uses_one_grouped_query(session_factory):
    _categories(session_factory)
    with session_factory() as db:
        statements = []

        def record(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(db.bind, "before_cursor_execute", record)
        try:
            rows = category_navigation(user=None, db=db)
        finally:
            event.remove(db.bind, "before_cursor_execute", record)
    assert len(rows) == 4
    assert len(statements) == 1
    assert "GROUP BY" in statements[0].upper()
