"""Every error message the API can return, in one place.

The frontend shows `error.message` verbatim to customers and pharmacists, so each one is
one or two plain, sentence-case sentences: what happened, then what to do next. The
`code` beside each message is the contract and never changes; the wording may.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.contracts import CartItem, OrderStatus

# ---------------------------------------------------------------------------
# 409 invalid_transition
# ---------------------------------------------------------------------------

REVIEW_TARGETS = {"verified", "rejected"}


def invalid_transition(current: OrderStatus, target: OrderStatus) -> str:
    if target == "placed":
        return {
            "pending_review": "A pharmacist is still checking this order. You can place it once it's verified.",
            "rejected": "The pharmacist couldn't approve this order, so it can't be placed. "
            "Please upload a new prescription.",
            "needs_prescription": "This order needs a prescription. "
            "Please upload a photo of your prescription to continue.",
            "placed": "This order has already been placed.",
        }.get(current, "This order can't be placed right now. Please refresh to see its latest status.")
    if target in REVIEW_TARGETS:
        return {
            "verified": "This order was already reviewed, so it can't be changed now.",
            "rejected": "This order was already reviewed, so it can't be changed now.",
            "placed": "This order has already been placed, so it can't be reviewed.",
            "confirmed_otc": "This order has only over-the-counter medicines, so it doesn't need a review.",
            "needs_prescription": "This order is waiting for the customer's prescription, "
            "so there's nothing to review yet.",
        }.get(current, "This order can't be reviewed right now. Please refresh to see its latest status.")
    return "This order can't be changed right now. Please refresh to see its latest status."


def swap_not_allowed(current: OrderStatus) -> str:
    if current == "needs_prescription":
        return "Please upload your prescription before choosing a generic for this order."
    return "This order was already reviewed, so its medicines can't be swapped now."


STALE_ORDER = "Someone else just updated this order. Please refresh and try again."

# ---------------------------------------------------------------------------
# 422 invalid_request
# ---------------------------------------------------------------------------


def item_name(item: CartItem) -> str:
    if item.sku is not None:
        return item.sku.brand_name
    if item.parsed is not None:
        return f"“{item.parsed.raw_text.strip()}”"
    return f"“{(item.requested_text or 'this medicine').strip()}”"


def no_generic(item: CartItem) -> str:
    return f"There's no cheaper generic for {item_name(item)}, so it stays as it is."


UNKNOWN_ITEM = "One of those medicines isn't on this order any more. Please refresh and try again."
DUPLICATE_ITEM = "The same medicine was listed twice. Please choose one action for each medicine."
UNKNOWN_SKU = "We couldn't find that product in the catalog. Please search again and pick another."


def item_without_sku(item: CartItem) -> str:
    return (
        f"{item_name(item)} isn't matched to a product yet. "
        "Please choose a product for it or remove it before approving."
    )


def edit_needs_change(item: CartItem) -> str:
    return f"Please choose a new product or quantity for {item_name(item)}, or approve it as it is."


def nothing_matched(phrases: Iterable[str]) -> str:
    quoted = [f"“{p.strip()}”" for p in phrases if p.strip()]
    what = _join(quoted) if quoted else "any of those medicines"
    return f"We couldn't find {what} in our catalog. Try the brand name printed on the strip."


# Request bodies and query strings that fail validation, by field name.
INVALID_FIELD = {
    "email": "Please enter a valid email address, like name@example.com.",
    "text": "Please type the medicines you need, in 500 characters or fewer.",
    "image": "Please attach a photo of the prescription.",
    "q": "Please type at least one letter to search, in 100 characters or fewer.",
    "limit": "Search can show between 1 and 20 results.",
    "quantity_packs": "Quantity must be at least 1 pack.",
    "decision": "Please choose to approve or reject the order.",
    "action": "Please choose approve, edit or remove for each medicine.",
    "item_id": "Please say which medicine you mean.",
    "use_generic": "Please say whether to use the generic.",
}
INVALID_REQUEST = "Something in that request wasn't right. Please check it and try again."

# ---------------------------------------------------------------------------
# 404
# ---------------------------------------------------------------------------

ORDER_NOT_FOUND = "We couldn't find that order. Please check the link or start a new order."
ORDER_IMAGE_NOT_FOUND = "There's no prescription photo for this order."
SAMPLE_NOT_FOUND = "That sample prescription isn't available. Please pick another sample."
PAGE_NOT_FOUND = "We couldn't find that page. Please check the address."
NO_FORECAST = "The demand forecast hasn't been calculated yet. Please check back in a minute."
SKU_FORECAST_NOT_FOUND = (
    "There's no forecast for that medicine in this area yet. Try another medicine or area."
)

# ---------------------------------------------------------------------------
# Uploads, parser, rate limit, server
# ---------------------------------------------------------------------------

UNSUPPORTED_TYPE = "We can only read JPEG, PNG or WebP photos. Please send the prescription as a photo."
UNREADABLE_IMAGE = "We couldn't open that image. Please take a new photo of the prescription and try again."


def image_too_large(max_mb: int) -> str:
    return f"That photo is too large. Please send one smaller than {max_mb} MB."


def rate_limited(minutes: int) -> str:
    # The frontend reads the number of minutes out of this message; keep it the only number.
    unit = "minute" if minutes == 1 else "minutes"
    return (
        "You've reached the hourly limit for prescription uploads. "
        f"Please try again in {minutes} {unit}, or try a sample prescription."
    )


PARSER_FAILED = (
    "We couldn't read that prescription. Please try a clearer photo, or try a sample prescription."
)
PARSER_TIMEOUT = "Reading the prescription took too long. Please try again, or try a sample prescription."
INTERNAL_ERROR = "Something went wrong on our side. Please try again in a moment."
REQUEST_FAILED = "We couldn't handle that request. Please try again."


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " or " + parts[-1]
