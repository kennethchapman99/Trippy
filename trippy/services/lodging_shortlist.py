"""Source-aware lodging shortlist generation."""

from __future__ import annotations

from urllib.parse import urlparse

from trippy.models.shortlists import (
    LiveDataStatus,
    LodgingFitCategory,
    LodgingOption,
    RecommendationGrade,
    ResearchShortlistState,
    ShortlistCategory,
)
from trippy.models.sources import TravelSourceCategory
from trippy.models.trip_planning import TripIntake
from trippy.services.destination_profiles import profile_for_intake
from trippy.services.live_validation import LiveValidationService
from trippy.services.shortlist_store import (
    ShortlistContext,
    ShortlistStore,
    source_plan,
    source_plan_payload,
    source_search_url,
    target_matches_selected_regions,
)
from trippy.services.source_research import SourceResearchService
from trippy.services.trip_intake import TripIntakeService
from trippy.services.trip_planner import TripPlannerService


class LodgingShortlistService:
    """Build family-fit lodging candidates from destination profile targets."""

    def __init__(
        self,
        intake_service: TripIntakeService | None = None,
        planner_service: TripPlannerService | None = None,
        store: ShortlistStore | None = None,
    ) -> None:
        self._intakes = intake_service or TripIntakeService()
        self._planner = planner_service or TripPlannerService(self._intakes)
        self._store = store or ShortlistStore()

    def build(
        self,
        trip_id: str,
        *,
        validate_live: bool | None = None,
        deep_research: bool = False,
        adapter_mode: str = "auto",
    ) -> ResearchShortlistState:
        ctx = ShortlistContext(
            trip_id,
            intake_service=self._intakes,
            planner_service=self._planner,
        )
        profile = profile_for_intake(ctx.intake)
        category = (
            TravelSourceCategory.PRIVATE_LODGING
            if any("Pico" in region or "Faial" in region for region in ctx.option.regions)
            else TravelSourceCategory.CITY_LODGING
        )
        plan = source_plan(category)
        options = _options_from_profile(profile, ctx.intake, ctx.option.regions)
        recommended = next(
            (
                option.option_id
                for option in options
                if option.recommendation_grade == RecommendationGrade.GOOD
            ),
            options[0].option_id if options else None,
        )
        state = ResearchShortlistState(
            trip_id=trip_id,
            category=ShortlistCategory.LODGING,
            selected_plan_option_id=ctx.draft.selected_option_id or ctx.draft.recommended_option_id,
            source_routing=source_plan_payload(plan),
            lodging_options=options,
            recommended_option_id=recommended,
            recommendation_summary=(
                "Prioritize lodging that proves 3+ beds, parking/access clarity, and safe practical "
                "location before optimizing price. Queen-bed compromises remain conditional."
            ),
            warnings=[
                "Exact room/rental availability and bed layout must be verified live before recommendation handoff.",
                "Two-room hotel solutions can work, but only if total comfort beats a private rental.",
            ],
            next_actions=[
                "Open the recommended option source link and validate 5-person occupancy.",
                "Reject any option that cannot explicitly prove 3+ beds.",
                "Cross-check location and review/safety signals on Tripadvisor or Booking.com.",
            ],
        )
        LiveValidationService().validate_state(state, attempt_network=validate_live)
        if deep_research:
            SourceResearchService().research_state(state, adapter_mode=adapter_mode)
        return self._store.save(state)

    def add_candidate(
        self,
        trip_id: str,
        *,
        link: str,
        notes: str = "",
        name: str = "",
        validate_live: bool | None = None,
        deep_research: bool = False,
        adapter_mode: str = "auto",
    ) -> ResearchShortlistState:
        """Add a user-supplied lodging candidate into the canonical lodging shortlist."""
        if not link.strip() and not notes.strip():
            raise ValueError("lodging candidate requires a link or notes")
        ctx = ShortlistContext(
            trip_id,
            intake_service=self._intakes,
            planner_service=self._planner,
        )
        state = self._store.load(trip_id, ShortlistCategory.LODGING)
        if state is None:
            state = self.build(trip_id, validate_live=False)
        option = _user_candidate_option(
            state,
            ctx.intake,
            link=link.strip(),
            notes=notes.strip(),
            name=name.strip(),
        )
        state.lodging_options.append(option)
        state.lodging_options.sort(key=lambda item: item.rank)
        state.recommendation_summary = (
            state.recommendation_summary
            + " User-supplied candidates are scored in the same lodging model and should be validated against sourced options."
        )
        state.next_actions.insert(
            0,
            "Review the user-supplied lodging candidate against bed, location, parking, cancellation, and value.",
        )
        LiveValidationService().validate_state(state, attempt_network=validate_live)
        if deep_research:
            SourceResearchService().research_state(
                state,
                adapter_mode=adapter_mode,
                option_ids=[option.option_id],
            )
        return self._store.save(state)


def _options_from_profile(
    profile: object,
    intake: TripIntake,
    selected_regions: list[str],
) -> list[LodgingOption]:
    targets = [
        target
        for target in getattr(profile, "lodging_search_targets", [])
        if target_matches_selected_regions(
            target,
            selected_regions,
            getattr(profile, "island_or_region_terms", []),
        )
    ]
    party = intake.party
    traveler_count = party.total_travelers
    requires_three_beds = traveler_count >= 5 or getattr(party, "children", 0) >= 2
    privacy_needed = bool(
        getattr(party, "separate_rooms_preferred", False) or getattr(party, "privacy_needs", None)
    )
    options: list[LodgingOption] = []
    for idx, target in enumerate(targets[:5], start=1):
        source = "Booking.com" if target.get("lodging_type") != "private rental" else "Airbnb"
        validation = {
            "Tripadvisor": source_search_url("Tripadvisor", str(target["query"])),
            "Booking.com": source_search_url("Booking.com", str(target["query"])),
        }
        is_private = target.get("lodging_type") == "private rental"
        bed_fit_known = True if is_private else None
        king_known = None
        parking = (
            "likely practical but live-verify exact property parking"
            if is_private
            else "verify paid/free parking and loading access"
        )
        flags = []
        if requires_three_beds and bed_fit_known is None:
            flags.append("family 3-bed layout is not proven")
        if king_known is None:
            flags.append("king-bed preference is unverified")
        if not is_private:
            flags.append(f"hotel may require two rooms for {traveler_count} traveler(s)")
        if privacy_needed and not is_private:
            flags.append("separate-room/privacy needs must be proven")
        fit_category = _fit_category(
            is_private=is_private,
            bed_fit_known=bed_fit_known,
            privacy_needed=privacy_needed,
            traveler_count=traveler_count,
            flags=flags,
        )
        score = 22 + len(flags) * 8
        comfort = 86 - len(flags) * 8 + (4 if is_private else 0)
        options.append(
            LodgingOption(
                option_id=f"lodging-{idx}",
                rank=idx,
                source=source,
                name=str(target["name"]),
                location_area=str(target["location_area"]),
                island_or_region=str(target["island_or_region"]),
                lodging_type=str(target["lodging_type"]),
                room_layout="whole-home/unit target"
                if is_private
                else "hotel room or two-room setup; live-verify",
                bed_layout="target 3+ beds; exact layout must be live-verified",
                adult_child_fit=(
                    f"Validate {party.adults} adult(s), {party.children} child(ren), "
                    f"{traveler_count} traveler(s) total."
                ),
                traveler_roster_supported=bed_fit_known,
                min_three_beds_satisfied=bed_fit_known,
                king_bed_preference_satisfied=king_known,
                family_of_five_fit=bed_fit_known if traveler_count >= 5 else None,
                separate_room_privacy_fit=True if is_private else None,
                occupancy_fit=(
                    f"Technically plausible for {traveler_count} traveler(s), but live occupancy must be confirmed."
                    if bed_fit_known is not False
                    else f"Does not currently prove occupancy for {traveler_count} traveler(s)."
                ),
                comfort_fit=_comfort_fit(fit_category, party.summary()),
                fit_category=fit_category,
                bed_layout_confidence=0.62 if is_private else 0.28,
                current_availability_signal="not live-checked yet",
                current_price_signal="estimated/search handoff only",
                parking_practicality=parking,
                driving_practicality="good only if roads, driveway, and loading access are clear",
                walkability="validate restaurants/groceries and whether driving is required every meal",
                cancellation_notes="live-verify free cancellation/refund deadline before handoff",
                price_band="live verify; compare total stay cost including taxes/fees",
                deep_link=source_search_url(source, str(target["query"])),
                validation_links=validation,
                friction_score=score,
                family_comfort_score=comfort,
                recommendation_grade=RecommendationGrade.GOOD
                if is_private
                else RecommendationGrade.CONDITIONAL,
                tradeoffs=[
                    "Private space usually fits Azores island travel if location, safety, and parking are strong."
                    if is_private
                    else "Boutique hotel comfort can be excellent, but family bed fit may require two rooms.",
                    "Do not advance unless occupancy, beds, cancellation, and access are explicit.",
                ],
                friction_flags=flags,
                confidence_notes=[
                    "Source link starts exact validation; availability is not asserted."
                ],
                live_data_status=LiveDataStatus.HANDOFF_REQUIRED,
            )
        )
    return options


def _user_candidate_option(
    state: ResearchShortlistState,
    intake: TripIntake,
    *,
    link: str,
    notes: str,
    name: str,
) -> LodgingOption:
    party = intake.party
    traveler_count = party.total_travelers
    source = _source_from_link(link)
    lower = f"{link} {notes} {name}".lower()
    is_private = any(token in lower for token in ["airbnb", "vrbo", "villa", "home", "rental"])
    three_beds = _mentions_three_beds(lower)
    king = True if "king" in lower else None
    parking_known = "parking" in lower or "park" in lower
    privacy_needed = bool(party.separate_rooms_preferred or party.privacy_needs)
    flags = []
    if traveler_count >= 5 and three_beds is not True:
        flags.append("user candidate does not yet prove 3+ beds for the roster")
    if king is None:
        flags.append("king-bed preference not proven")
    if privacy_needed and not is_private:
        flags.append("privacy/separate-room fit is not proven")
    if not parking_known:
        flags.append("parking/access practicality not proven")
    if "cancel" not in lower and "refundable" not in lower:
        flags.append("cancellation terms not provided")

    rank = max((option.rank for option in state.lodging_options), default=0) + 1
    option_id = f"user-lodging-{rank}"
    fit_category = (
        LodgingFitCategory.PREFERRED
        if three_beds and (king or traveler_count < 5) and parking_known
        else LodgingFitCategory.COMFORTABLE
        if three_beds
        else LodgingFitCategory.TECHNICAL
    )
    friction = min(90, 18 + len(flags) * 10)
    comfort = max(35, 88 - len(flags) * 9 + (4 if is_private else 0))
    display_name = name or _name_from_link(link) or "User lodging candidate"
    price = _price_signal(notes)
    return LodgingOption(
        option_id=option_id,
        rank=rank,
        source=source,
        name=display_name,
        location_area=_location_hint(notes, intake),
        island_or_region=", ".join(intake.destination_seeds) or "destination TBD",
        lodging_type="private rental" if is_private else "hotel/listing candidate",
        room_layout="user-supplied candidate; parse and validate exact room/unit terms",
        bed_layout="user notes suggest 3+ beds" if three_beds else "bed layout not proven from supplied notes",
        adult_child_fit=(
            f"Evaluate for {party.adults} adult(s), {party.children} child(ren), "
            f"{traveler_count} traveler(s) total."
        ),
        traveler_roster_supported=True if three_beds else None,
        min_three_beds_satisfied=True if three_beds else None,
        king_bed_preference_satisfied=king,
        family_of_five_fit=True if traveler_count >= 5 and three_beds else None,
        separate_room_privacy_fit=True if is_private and privacy_needed else None,
        occupancy_fit=(
            f"User candidate may fit {traveler_count} traveler(s); exact occupancy must be confirmed on source."
        ),
        comfort_fit=_comfort_fit(fit_category, party.summary()),
        fit_category=fit_category,
        bed_layout_confidence=0.68 if three_beds else 0.22,
        current_availability_signal="user-supplied; live source still required",
        current_price_signal=price or "not supplied",
        parking_practicality="parking mentioned; verify exact access" if parking_known else "not proven",
        driving_practicality="validate road access, driveway/loading, and daily drive burden",
        walkability="validate food/grocery/activity access from exact location",
        cancellation_notes="mentioned in notes; verify deadline" if "cancel" in lower else "not supplied",
        price_band=price or "not supplied",
        deep_link=link,
        validation_links={
            "Tripadvisor": source_search_url("Tripadvisor", f"{display_name} {intake.travel_window.display()}"),
            "Booking.com": source_search_url("Booking.com", f"{display_name} {intake.travel_window.display()}"),
        },
        friction_score=friction,
        family_comfort_score=comfort,
        recommendation_grade=RecommendationGrade.GOOD
        if fit_category in {LodgingFitCategory.PREFERRED, LodgingFitCategory.COMFORTABLE}
        else RecommendationGrade.CONDITIONAL,
        tradeoffs=[
            "User-supplied option is compared in the same shortlist model as sourced options.",
            "Promote only after exact bed layout, total price, cancellation, location, and access are verified.",
        ],
        friction_flags=flags,
        confidence_notes=[
            "Candidate came from user input, not autonomous sourcing.",
            notes or "No extra user notes supplied.",
        ],
        live_data_status=LiveDataStatus.HANDOFF_REQUIRED,
    )


def _source_from_link(link: str) -> str:
    host = urlparse(link).netloc.lower()
    if "booking" in host:
        return "Booking.com"
    if "airbnb" in host:
        return "Airbnb"
    if "vrbo" in host:
        return "VRBO"
    if "expedia" in host:
        return "Expedia"
    if "tripadvisor" in host:
        return "Tripadvisor"
    return "User supplied"


def _name_from_link(link: str) -> str:
    parsed = urlparse(link)
    pieces = [piece for piece in parsed.path.split("/") if piece]
    if pieces:
        return pieces[-1].replace("-", " ").replace("_", " ").title()[:80]
    return parsed.netloc or ""


def _mentions_three_beds(text: str) -> bool:
    return any(
        token in text
        for token in [
            "3 bed",
            "three bed",
            "3-bedroom",
            "3 bedroom",
            "3br",
            "4 bed",
            "4-bedroom",
            "4 bedroom",
            "4br",
        ]
    )


def _price_signal(notes: str) -> str:
    tokens = [token.strip(",.;") for token in notes.replace("\n", " ").split()]
    for index, token in enumerate(tokens):
        upper = token.upper()
        if "$" in token:
            return token
        if upper in {"CAD", "USD", "EUR"} and index + 1 < len(tokens):
            return f"{token} {tokens[index + 1]}"
        if upper.startswith(("CAD", "USD", "EUR")):
            return token
    return ""


def _location_hint(notes: str, intake: TripIntake) -> str:
    if notes:
        first = notes.split(".")[0].strip()
        if first:
            return first[:90]
    return ", ".join(intake.destination_seeds) or "location TBD"


def _fit_category(
    *,
    is_private: bool,
    bed_fit_known: bool | None,
    privacy_needed: bool,
    traveler_count: int,
    flags: list[str],
) -> LodgingFitCategory:
    if traveler_count >= 5 and bed_fit_known is None:
        return LodgingFitCategory.TECHNICAL
    if flags and not is_private:
        return LodgingFitCategory.WEAK
    if is_private and not privacy_needed:
        return LodgingFitCategory.PREFERRED
    if is_private:
        return LodgingFitCategory.COMFORTABLE
    return LodgingFitCategory.TECHNICAL


def _comfort_fit(fit_category: LodgingFitCategory, party_summary: str) -> str:
    value = fit_category.value
    if value == "preferred_fit":
        return f"Clearly preferred if live listing confirms beds/parking for {party_summary}."
    if value == "comfortable_fit":
        return f"Actually comfortable if privacy/access details hold for {party_summary}."
    if value == "weak_fit":
        return f"Technically possible but likely uncomfortable or admin-heavy for {party_summary}."
    return f"Technical fit only until live bed/privacy details are proven for {party_summary}."
