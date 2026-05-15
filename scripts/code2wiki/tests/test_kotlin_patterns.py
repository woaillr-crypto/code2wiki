"""Unit tests for the Ktor route extractor.

The extractor must correctly handle:
  - flat routing { get("/x") {} }
  - nested route("/api") { route("/v1") { get("/users") {} } } stitching
  - braces inside string literals (must not trip the state machine)
  - line comments (//) and block comments (/* */)
  - triple-quoted Kotlin raw strings
  - HTTP method calls without trailing { (no body)
  - free-standing HTTP method calls outside routing { } (must be ignored)
  - depth-limit safety net
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parents[2]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import pytest

from code2wiki.plugins.language_kotlin import extract_ktor_routes


# ──────────────────────────────────────────────────────────────────────────────
# Flat / shallow
# ──────────────────────────────────────────────────────────────────────────────

def test_flat_routing_block():
    src = """
    fun Application.module() {
        routing {
            get("/health") {
                call.respondText("ok")
            }
        }
    }
    """
    assert extract_ktor_routes(src) == [("GET", "/health")]


def test_multiple_verbs_in_routing_block():
    src = """
    routing {
        get("/users") { }
        post("/users") { }
        put("/users/{id}") { }
        delete("/users/{id}") { }
    }
    """
    assert extract_ktor_routes(src) == [
        ("GET", "/users"),
        ("POST", "/users"),
        ("PUT", "/users/{id}"),
        ("DELETE", "/users/{id}"),
    ]


def test_route_prefix_is_stitched():
    src = """
    routing {
        route("/api/v1") {
            get("/users") { }
            post("/users") { }
        }
    }
    """
    assert extract_ktor_routes(src) == [
        ("GET", "/api/v1/users"),
        ("POST", "/api/v1/users"),
    ]


def test_two_levels_of_nesting():
    src = """
    routing {
        route("/api") {
            route("/v1") {
                get("/orders") { }
                route("/{orderId}") {
                    get("/items") { }
                }
            }
        }
    }
    """
    assert extract_ktor_routes(src) == [
        ("GET", "/api/v1/orders"),
        ("GET", "/api/v1/{orderId}/items"),
    ]


def test_empty_path_arguments():
    """Some Ktor projects use get("") inside route() to match the prefix exactly."""
    src = """
    routing {
        route("/health") {
            get("") { }
        }
    }
    """
    assert extract_ktor_routes(src) == [("GET", "/health")]


def test_root_only():
    src = """
    routing {
        get("/") { }
    }
    """
    assert extract_ktor_routes(src) == [("GET", "/")]


# ──────────────────────────────────────────────────────────────────────────────
# Free-standing verb calls outside routing — must be ignored
# ──────────────────────────────────────────────────────────────────────────────

def test_verb_outside_routing_is_ignored():
    """A `get(...)` call in a non-routing context (e.g. HTTP client code) must
    not produce a fake route."""
    src = """
    suspend fun fetchUser(id: Long): User {
        val resp = client.get("/external/user/$id")
        return resp.body()
    }
    """
    assert extract_ktor_routes(src) == []


def test_verb_in_lambda_body_inside_routing():
    """A verb call buried inside a non-route lambda still has routing as an
    ancestor scope, so it should be picked up. This is technically over-broad
    but mirrors how the regex-first design works in practice — fixture cases
    that exercise this are uncommon."""
    src = """
    routing {
        route("/api") {
            get("/legit") {
                // not a real route call, but extractor sees it
                val x = listOf(1).map { x ->
                    post("/leaked")  // <-- this gets picked up
                    x
                }
            }
        }
    }
    """
    routes = extract_ktor_routes(src)
    # The legit route is always picked up.
    assert ("GET", "/api/legit") in routes


# ──────────────────────────────────────────────────────────────────────────────
# String / comment safety
# ──────────────────────────────────────────────────────────────────────────────

def test_braces_inside_string_literal_do_not_confuse_stack():
    src = """
    routing {
        route("/users") {
            get("/{id}") {
                val msg = "hello } { world"
                call.respondText(msg)
            }
            post("/create") { }
        }
    }
    """
    routes = extract_ktor_routes(src)
    assert routes == [
        ("GET", "/users/{id}"),
        ("POST", "/users/create"),
    ]


def test_braces_inside_triple_quoted_string_ignored():
    src = '''
    routing {
        route("/raw") {
            get("/json") {
                val template = """
                    { "level1": { "level2": "value" } }
                """
                call.respondText(template)
            }
        }
    }
    '''
    assert extract_ktor_routes(src) == [("GET", "/raw/json")]


def test_braces_inside_line_comment_ignored():
    src = """
    routing {
        route("/api") {
            // TODO refactor { this } block
            get("/v1") { }
        }
    }
    """
    assert extract_ktor_routes(src) == [("GET", "/api/v1")]


def test_braces_inside_block_comment_ignored():
    src = """
    routing {
        route("/api") {
            /* example: { "key": "value" } */
            get("/v1") { }
        }
    }
    """
    assert extract_ktor_routes(src) == [("GET", "/api/v1")]


def test_path_with_curly_braces_path_params():
    """Ktor uses {paramName} syntax in route paths; the braces are inside the
    string literal and must not affect scope tracking."""
    src = """
    routing {
        route("/users/{id}") {
            get("/posts/{postId}") { }
        }
    }
    """
    assert extract_ktor_routes(src) == [("GET", "/users/{id}/posts/{postId}")]


# ──────────────────────────────────────────────────────────────────────────────
# Reject / fall-through
# ──────────────────────────────────────────────────────────────────────────────

def test_no_routing_block_returns_empty():
    src = """
    class UserService {
        fun getUser(id: Long): User = ...
    }
    """
    assert extract_ktor_routes(src) == []


def test_empty_string_returns_empty():
    assert extract_ktor_routes("") == []


def test_routing_without_any_verbs_returns_empty():
    src = """
    routing {
        // empty routing block
    }
    """
    assert extract_ktor_routes(src) == []


# ──────────────────────────────────────────────────────────────────────────────
# Edge cases — path normalization
# ──────────────────────────────────────────────────────────────────────────────

def test_trailing_slash_in_prefix_collapsed():
    src = """
    routing {
        route("/api/") {
            get("/users") { }
        }
    }
    """
    assert extract_ktor_routes(src) == [("GET", "/api/users")]


def test_leading_slash_in_verb_path_handled():
    src = """
    routing {
        route("api") {
            get("users") { }
        }
    }
    """
    # Both segments are missing leading /, output normalizes.
    assert extract_ktor_routes(src) == [("GET", "/api/users")]


def test_consecutive_slashes_collapsed():
    src = """
    routing {
        route("/api//v1/") {
            get("//users") { }
        }
    }
    """
    assert extract_ktor_routes(src) == [("GET", "/api/v1/users")]


# ──────────────────────────────────────────────────────────────────────────────
# Multiple top-level routing blocks
# ──────────────────────────────────────────────────────────────────────────────

def test_multiple_routing_blocks_are_independent():
    """Some apps split routing across modules. Each routing { } has its own
    scope stack."""
    src = """
    routing {
        route("/api") {
            get("/users") { }
        }
    }
    routing {
        route("/admin") {
            get("/dashboard") { }
        }
    }
    """
    assert extract_ktor_routes(src) == [
        ("GET", "/api/users"),
        ("GET", "/admin/dashboard"),
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Depth safety
# ──────────────────────────────────────────────────────────────────────────────

def test_deeply_nested_routes_do_not_crash():
    """Pathological deep nesting must complete (depth limit enforces this)."""
    depth = 20
    src = "routing {\n" + "".join(f'route("/l{i}") {{\n' for i in range(depth)) \
        + 'get("/leaf") { }\n' + "}\n" * depth + "}\n"
    routes = extract_ktor_routes(src, max_depth=8)
    # We should still get a route (possibly truncated) but not crash.
    assert isinstance(routes, list)


def test_unbalanced_braces_do_not_crash():
    """Malformed code with more `}` than `{` must not raise."""
    src = """
    routing {
        get("/x") { }
        }  // extra
    }
    """
    routes = extract_ktor_routes(src)
    # Should at least extract the one valid verb.
    assert ("GET", "/x") in routes


# ──────────────────────────────────────────────────────────────────────────────
# Real-world style snippet
# ──────────────────────────────────────────────────────────────────────────────

def test_realistic_module_layout():
    src = '''
    package com.example.app

    import io.ktor.server.application.*
    import io.ktor.server.routing.*

    fun Application.orderRoutes() {
        routing {
            route("/api/order") {
                get("/list") {
                    val items = service.list()
                    call.respond(items)
                }
                post("/create") {
                    val req = call.receive<CreateOrder>()
                    service.create(req)
                    call.respondText("ok")
                }
                route("/{orderId}") {
                    get { call.respond(service.get(call.parameters["orderId"]!!.toLong())) }
                    put("/status") {
                        // update status flow
                        val body = """
                            { "next": "PAID" }
                        """
                        service.updateStatus(body)
                    }
                }
            }
        }
    }
    '''
    routes = extract_ktor_routes(src)
    assert ("GET", "/api/order/list") in routes
    assert ("POST", "/api/order/create") in routes
    assert ("PUT", "/api/order/{orderId}/status") in routes
