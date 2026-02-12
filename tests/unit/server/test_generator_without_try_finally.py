"""Test to demonstrate what happens when a generator provider doesn't use try-finally.

This test shows that:
1. Without try-finally, cleanup code after yield won't run when an exception occurs
2. This causes a resource leak for that specific provider
3. BUT the DI system as a whole continues to work correctly
4. The original exception is still properly raised to the caller
"""

import pytest
from s2auth.common.dependencies import (
    Depends,
    inject,
    register_provider,
    setup,
)


# Track whether cleanup code runs
cleanup_tracker = {"broken_cleanup_ran": False, "proper_cleanup_ran": False}


@register_provider()
async def broken_provider_no_try():
    """A generator provider WITHOUT try-finally (BROKEN pattern)."""
    cleanup_tracker["broken_cleanup_ran"] = False
    resource = "broken_resource"
    yield resource
    # This cleanup code WON'T run when an exception occurs! ❌
    cleanup_tracker["broken_cleanup_ran"] = True


@register_provider()
async def proper_provider_with_try():
    """A generator provider WITH try-finally (CORRECT pattern)."""
    cleanup_tracker["proper_cleanup_ran"] = False
    resource = "proper_resource"
    try:
        yield resource
    finally:
        # This cleanup code WILL run even when an exception occurs! ✅
        cleanup_tracker["proper_cleanup_ran"] = True


@inject
async def use_broken_provider(resource: str = Depends[broken_provider_no_try]):
    """Function that uses the broken provider and raises an exception."""
    assert resource == "broken_resource"
    raise ValueError("Something went wrong!")


@inject
async def use_proper_provider(resource: str = Depends[proper_provider_with_try]):
    """Function that uses the proper provider and raises an exception."""
    assert resource == "proper_resource"
    raise ValueError("Something went wrong!")


@inject
async def use_broken_provider_success(resource: str = Depends[broken_provider_no_try]):
    """Function that uses the broken provider and succeeds."""
    assert resource == "broken_resource"
    return "success"


@pytest.mark.skip_wire
@pytest.mark.asyncio
async def test_broken_provider_cleanup_doesnt_run_on_exception():
    """Demonstrates that cleanup code won't run without try-finally when exception occurs."""
    setup()

    # Reset tracker
    cleanup_tracker["broken_cleanup_ran"] = False

    # Call function that raises an exception
    with pytest.raises(ValueError, match="Something went wrong!"):
        await use_broken_provider()

    # ❌ Cleanup code did NOT run - resource leak!
    assert cleanup_tracker["broken_cleanup_ran"] is False, (
        "Cleanup code should NOT have run for broken provider (no try-finally)"
    )


@pytest.mark.skip_wire
@pytest.mark.asyncio
async def test_proper_provider_cleanup_runs_on_exception():
    """Demonstrates that cleanup code WILL run with try-finally when exception occurs."""
    setup()

    # Reset tracker
    cleanup_tracker["proper_cleanup_ran"] = False

    # Call function that raises an exception
    with pytest.raises(ValueError, match="Something went wrong!"):
        await use_proper_provider()

    # ✅ Cleanup code DID run - proper resource management!
    assert cleanup_tracker["proper_cleanup_ran"] is True, (
        "Cleanup code should have run for proper provider (with try-finally)"
    )


@pytest.mark.skip_wire
@pytest.mark.asyncio
async def test_broken_provider_cleanup_runs_on_success():
    """Demonstrates that cleanup code WILL run even without try-finally on success path."""
    setup()

    # Reset tracker
    cleanup_tracker["broken_cleanup_ran"] = False

    # Call function that succeeds (no exception)
    result = await use_broken_provider_success()
    assert result == "success"

    # ✅ Cleanup code DID run on success path (uses __anext__(), not throw())
    assert cleanup_tracker["broken_cleanup_ran"] is True, (
        "Cleanup code should have run on success path, even without try-finally"
    )


@pytest.mark.skip_wire
@pytest.mark.asyncio
async def test_di_system_continues_working_after_broken_cleanup():
    """Demonstrates that the DI system doesn't break even when cleanup fails."""
    setup()

    # First, use the broken provider (cleanup won't run)
    cleanup_tracker["broken_cleanup_ran"] = False
    with pytest.raises(ValueError):
        await use_broken_provider()
    assert cleanup_tracker["broken_cleanup_ran"] is False

    # Now, use the proper provider - DI system still works! ✅
    cleanup_tracker["proper_cleanup_ran"] = False
    with pytest.raises(ValueError):
        await use_proper_provider()
    assert cleanup_tracker["proper_cleanup_ran"] is True

    # DI system is still functional!


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
