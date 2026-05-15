"""Unit tests for TypeScript-plugin specific regex and parsers.

Phase 1.2 focus: Prisma schema parsing.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parents[2]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from code2wiki.plugins.language_typescript import parse_prisma_schema


# ──────────────────────────────────────────────────────────────────────────────
# Basic model extraction
# ──────────────────────────────────────────────────────────────────────────────

def test_single_model_no_map_uses_model_name_as_table():
    src = """
    model User {
      id    Int    @id @default(autoincrement())
      email String @unique
      name  String
    }
    """
    result = parse_prisma_schema(src)
    assert len(result) == 1
    assert result[0]["name"] == "User"
    assert result[0]["table"] == "User"  # no @@map → defaults to model name


def test_single_model_with_map_uses_table_override():
    src = """
    model User {
      id    Int    @id
      email String

      @@map("t_user")
    }
    """
    result = parse_prisma_schema(src)
    assert result[0]["table"] == "t_user"


def test_multiple_models_each_has_correct_table():
    src = """
    model Order {
      id     Int
      amount Int

      @@map("t_order")
    }

    model Customer {
      id   Int
      name String
    }

    model Refund {
      id Int

      @@map("t_refund_log")
    }
    """
    result = parse_prisma_schema(src)
    names = [m["name"] for m in result]
    tables = [m["table"] for m in result]
    assert names == ["Order", "Customer", "Refund"]
    assert tables == ["t_order", "Customer", "t_refund_log"]


# ──────────────────────────────────────────────────────────────────────────────
# Field extraction
# ──────────────────────────────────────────────────────────────────────────────

def test_fields_are_extracted_with_type():
    src = """
    model Order {
      id     Int    @id
      userId Int
      amount Int
      status String
    }
    """
    result = parse_prisma_schema(src)
    fields = result[0]["fields"]
    field_names = [f["name"] for f in fields]
    assert "id" in field_names
    assert "userId" in field_names
    assert "amount" in field_names
    assert "status" in field_names

    # Type is attached
    id_field = next(f for f in fields if f["name"] == "id")
    assert id_field["type"] == "Int"


def test_optional_fields_have_question_mark_in_type():
    src = """
    model User {
      id    Int     @id
      name  String?
    }
    """
    result = parse_prisma_schema(src)
    fields = result[0]["fields"]
    name_field = next(f for f in fields if f["name"] == "name")
    assert "?" in name_field["type"]


def test_list_fields_have_brackets_in_type():
    src = """
    model User {
      id    Int
      posts Post[]
    }
    """
    result = parse_prisma_schema(src)
    posts_field = next(f for f in result[0]["fields"] if f["name"] == "posts")
    assert "[]" in posts_field["type"]


# ──────────────────────────────────────────────────────────────────────────────
# Comment / directive handling
# ──────────────────────────────────────────────────────────────────────────────

def test_inline_comments_stripped_before_field_match():
    src = """
    model User {
      id    Int    @id  // primary key
      email String       // contact
    }
    """
    result = parse_prisma_schema(src)
    field_names = [f["name"] for f in result[0]["fields"]]
    assert "id" in field_names
    assert "email" in field_names


def test_doc_comments_ignored():
    src = """
    /// User table — the canonical customer record.
    model User {
      id Int @id
    }
    """
    result = parse_prisma_schema(src)
    assert len(result) == 1
    assert result[0]["name"] == "User"


def test_at_at_directives_not_treated_as_fields():
    """@@map, @@index, @@unique, @@id are model-level, not field names."""
    src = """
    model Order {
      id Int

      @@map("t_order")
      @@index([id])
      @@unique([id])
    }
    """
    result = parse_prisma_schema(src)
    field_names = [f["name"] for f in result[0]["fields"]]
    # Field names must not include directives
    assert "@@map" not in field_names
    assert "@@index" not in field_names
    assert "@@unique" not in field_names


# ──────────────────────────────────────────────────────────────────────────────
# Negative / edge cases
# ──────────────────────────────────────────────────────────────────────────────

def test_empty_schema_returns_empty():
    assert parse_prisma_schema("") == []


def test_schema_without_models_returns_empty():
    """Generator + datasource only — no models defined."""
    src = """
    generator client {
      provider = "prisma-client-js"
    }

    datasource db {
      provider = "postgresql"
      url      = env("DATABASE_URL")
    }
    """
    assert parse_prisma_schema(src) == []


def test_enum_blocks_not_returned_as_models():
    """Prisma enums use `enum Foo { A B C }`, not `model Foo { ... }` — they
    must not be picked up as tables."""
    src = """
    enum Role {
      ADMIN
      USER
      GUEST
    }

    model User {
      id   Int  @id
      role Role
    }
    """
    result = parse_prisma_schema(src)
    names = [m["name"] for m in result]
    assert names == ["User"]
    assert "Role" not in names


def test_model_with_no_fields_returns_empty_fields_list():
    src = """
    model Empty {
    }
    """
    result = parse_prisma_schema(src)
    assert result[0]["fields"] == []


def test_model_with_only_map_directive():
    src = """
    model Audit {
      @@map("audit_log")
    }
    """
    result = parse_prisma_schema(src)
    assert result[0]["table"] == "audit_log"
    # @@map should NOT be in fields
    field_names = [f["name"] for f in result[0]["fields"]]
    assert "@@map" not in field_names


# ──────────────────────────────────────────────────────────────────────────────
# Realistic schema
# ──────────────────────────────────────────────────────────────────────────────

def test_realistic_prisma_schema():
    src = """
    generator client {
      provider = "prisma-client-js"
    }

    datasource db {
      provider = "postgresql"
      url      = env("DATABASE_URL")
    }

    /// User entity
    model User {
      id        Int      @id @default(autoincrement())
      email     String   @unique
      name      String?
      posts     Post[]
      createdAt DateTime @default(now())

      @@map("t_user")
      @@index([email])
    }

    model Post {
      id       Int     @id @default(autoincrement())
      title    String
      content  String?
      authorId Int
      author   User    @relation(fields: [authorId], references: [id])

      @@map("t_post")
    }

    enum Role {
      ADMIN
      USER
    }
    """
    result = parse_prisma_schema(src)
    # Exactly 2 models (enum excluded)
    assert len(result) == 2

    user = next(m for m in result if m["name"] == "User")
    assert user["table"] == "t_user"
    user_fields = [f["name"] for f in user["fields"]]
    assert "id" in user_fields
    assert "email" in user_fields
    assert "name" in user_fields
    assert "posts" in user_fields

    post = next(m for m in result if m["name"] == "Post")
    assert post["table"] == "t_post"
    post_fields = [f["name"] for f in post["fields"]]
    assert "authorId" in post_fields
