const state = {
  app: null,
  trip: null,
  activeTripId: null,
  activeStage: "start",
  lastWorkflowByStage: {},
  isCreatingTrip: false,
  suggestedIntake: null,
  ideaComparison: null,
  ideaRequest: null,
  ideaWorkflowId: null,
  ideaFeedback: {},
  showSuggestForm: false,
  openTripMenuId: null,
  flightSort: "best",
};

const stages = [
  { id: "start", label: "Start" },
  { id: "intake", label: "Intake" },
  { id: "options", label: "Options" },
  { id: "flights", label: "Flights" },
  { id: "lodging", label: "Lodging" },
  { id: "activities", label: "Activities" },
  { id: "plan", label: "Plan" },
  { id: "review", label: "Review" },
];

const partyOptions = [
  { value: "whole_family", label: "Whole family" },
  { value: "adults_only", label: "Adults only" },
  { value: "couple", label: "KenNSue" },
  { value: "subset_family", label: "Subset family" },
  { value: "family_plus_others", label: "Family plus others" },
  { value: "custom", label: "Custom" },
];

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("refreshButton").addEventListener("click", refresh);
  document.getElementById("generateTripButton").addEventListener("click", () => startGenerateIdeas());
  document.getElementById("newTripButton").addEventListener("click", () => startNewTrip());
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (target instanceof Element && !target.closest(".trip-menu-wrap") && state.openTripMenuId) {
      state.openTripMenuId = null;
      renderTripList();
    }
  });
  refresh();
});

async function refresh() {
  state.app = await apiGet("/api/state");
  if (!state.activeTripId && !state.isCreatingTrip) {
    state.activeTripId = state.app.suggested_trip_id;
  }
  if (state.activeTripId) {
    await loadTrip(state.activeTripId, { refreshApp: false });
  }
  if (state.activeTripId && state.activeStage === "start" && !state.showSuggestForm) {
    state.activeStage = nextUnlockedStage();
  }
  render();
}

async function loadTrip(tripId, options = {}) {
  if (options.refreshApp !== false) {
    state.app = await apiGet("/api/state");
  }
  state.isCreatingTrip = false;
  state.suggestedIntake = null;
  state.openTripMenuId = null;
  state.activeTripId = tripId;
  state.trip = await apiGet(`/api/trip?trip_id=${encodeURIComponent(tripId)}`);
  if (options.gotoNext) {
    state.activeStage = nextUnlockedStage();
  }
  render();
}

function startNewTrip(prefill = null) {
  state.activeTripId = null;
  state.trip = null;
  state.isCreatingTrip = true;
  state.suggestedIntake = prefill;
  state.activeStage = "intake";
  state.openTripMenuId = null;
  render();
  document.getElementById("stageBody")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function startGenerateIdeas() {
  state.activeTripId = null;
  state.trip = null;
  state.isCreatingTrip = false;
  state.suggestedIntake = null;
  state.ideaFeedback = {};
  state.activeStage = "start";
  state.showSuggestForm = true;
  state.openTripMenuId = null;
  render();
  document.querySelector(".wizard-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function apiGet(path) {
  const response = await fetch(path);
  return handleResponse(response);
}

async function apiPost(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse(response);
}

async function handleResponse(response) {
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Request failed");
  }
  return data;
}

function render() {
  normalizeActiveStage();
  renderHeader();
  renderTripList();
  renderStageTabs();
  renderStage();
  renderPicks();
  renderRunLog();
  wireProgressBar();
}

function renderHeader() {
  const intake = state.trip?.intake || state.suggestedIntake;
  document.querySelector(".command-band")?.classList.toggle("no-active-trip", !intake);
  const title = intake?.trip_name || "";
  const subhead = intake
    ? `${(intake.destination_seeds || []).join(", ")} · ${partyLabel(intake.party?.party_type)} · ${intake.party?.total_travelers || intake.travelers} traveler(s) · ${intake.duration_label || `${intake.duration_days || "?"} days`}`
    : "";
  document.getElementById("activeTripTitle").textContent = title;
  document.getElementById("activeTripSubhead").textContent = subhead;
  document.getElementById("logsJsonLink").href = state.activeTripId
    ? `/api/logs?trip_id=${encodeURIComponent(state.activeTripId)}`
    : "/api/logs";
  document.getElementById("planningProgress").innerHTML = planningProgressBar();
}

function normalizeActiveStage() {
  const legacyStageMap = {
    draft: "options",
    research: "flights",
    workspace: "plan",
    maps: "plan",
    feedback: "review",
  };
  state.activeStage = legacyStageMap[state.activeStage] || state.activeStage;
  if (!stages.some((stage) => stage.id === state.activeStage)) {
    state.activeStage = "start";
  }
  if (!isStageUnlocked(state.activeStage)) {
    state.activeStage = nextUnlockedStage();
  }
}

function isStageUnlocked(stageId) {
  const hasTrip = Boolean(state.activeTripId || state.trip?.intake);
  const hasIntake = Boolean(state.trip?.intake);
  const hasSelectedPlan = Boolean(state.trip?.draft?.selected_option_id);
  if (stageId === "start") return true;
  if (stageId === "intake") return state.isCreatingTrip || hasTrip;
  if (stageId === "options") return hasIntake;
  if (["flights", "lodging", "activities", "plan"].includes(stageId)) return hasSelectedPlan;
  if (stageId === "review") return hasTrip || Boolean(state.trip?.recent_workflows?.length);
  return false;
}

function isStageComplete(stageId) {
  if (stageId === "start") return Boolean(state.activeTripId || state.isCreatingTrip || state.suggestedIntake);
  if (stageId === "intake") return Boolean(state.trip?.intake);
  if (stageId === "options") return Boolean(state.trip?.draft?.selected_option_id);
  if (stageId === "flights") return Boolean(shortlistByCategory("flights")?.flight_options?.length);
  if (stageId === "lodging") return Boolean(shortlistByCategory("lodging")?.lodging_options?.length);
  if (stageId === "activities") {
    return Boolean(
      shortlistByCategory("activities")?.activity_options?.length ||
        shortlistByCategory("cars")?.car_options?.length,
    );
  }
  if (stageId === "plan") return Boolean(state.trip?.workspace || state.trip?.map_artifact);
  return Boolean(state.trip?.recent_workflows?.length);
}

function nextUnlockedStage() {
  if (state.isCreatingTrip || state.suggestedIntake) return "intake";
  if (!state.activeTripId && !state.trip?.intake) return "start";
  if (!state.trip?.intake) return "intake";
  if (!state.trip?.draft?.selected_option_id) return "options";
  if (!shortlistByCategory("flights")?.flight_options?.length) return "flights";
  if (!shortlistByCategory("lodging")?.lodging_options?.length) return "lodging";
  if (!shortlistByCategory("activities")?.activity_options?.length) return "activities";
  return "plan";
}

function guidedNextStep() {
  const stage = nextUnlockedStage();
  const messages = {
    start: "Choose Generate for ideas or New when you already know the trip.",
    intake: "Confirm who is going, timing, priorities, and comfort constraints.",
    options: "Build and choose the trip shape before exact recommendations.",
    flights: "Compare flight timing, friction, price bands, and source confidence.",
    lodging: "Decide one stay vs split stays, then compare places that fit the party.",
    activities: "Pick activities and car logic that fit the chosen trip shape.",
    plan: "Build the timeline, map, risks, and planning workspace.",
    review: "Send feedback only when a workflow should teach Trippy.",
  };
  return state.trip?.next_step || messages[stage] || messages.start;
}

function planningProgressBar() {
  if (!state.trip?.intake && !state.suggestedIntake) {
    return "";
  }
  const items = planningMilestones();
  return `<div class="progress-track" aria-label="Trip planning progress">
    ${items.map(progressStep).join("")}
  </div>`;
}

function planningMilestones() {
  const trip = state.trip || {};
  const draft = trip.draft;
  const workspace = trip.workspace;
  const hasIntake = Boolean(trip.intake || state.suggestedIntake);
  return [
    {
      key: "intake",
      icon: "I",
      label: "Intake",
      state: hasIntake ? "done" : "todo",
      detail: hasIntake ? "saved" : "needed",
    },
    {
      key: "shape",
      icon: "O",
      label: "Shape",
      state: draft?.selected_option_id ? "done" : draft?.options?.length ? "active" : "todo",
      detail: draft?.selected_option_id ? "selected" : draft?.options?.length ? "choose" : "draft",
    },
    shortlistMilestone("flights", "F", "Flights"),
    shortlistMilestone("lodging", "L", "Lodging"),
    shortlistMilestone("cars", "C", "Cars"),
    shortlistMilestone("activities", "A", "Activities"),
    {
      key: "workspace",
      icon: "S",
      label: "Sheet",
      state: workspace?.google_sheet_url ? "done" : workspace ? "active" : "todo",
      detail: workspace?.google_sheet_url ? "created" : workspace ? "local" : "build",
    },
    {
      key: "booked",
      icon: "B",
      label: "Booked",
      state: bookingMilestoneState(),
      detail: bookingMilestoneDetail(),
    },
  ];
}

function shortlistMilestone(category, icon, label) {
  const shortlist = shortlistByCategory(category);
  if (!shortlist) {
    return { key: category, icon, label, state: "todo", detail: "needed" };
  }
  const options = shortlistOptions(shortlist);
  const approved = options.some((option) => option.row_status === "approved" || option.row_status === "booked");
  const booked = options.some((option) => option.row_status === "booked");
  return {
    key: category,
    icon,
    label,
    state: booked || approved ? "done" : options.length ? "active" : "todo",
    detail: booked ? "booked" : approved ? "approved" : `${options.length} found`,
  };
}

function bookingMilestoneState() {
  const options = (state.trip?.shortlists || []).flatMap(shortlistOptions);
  const flightBooked = options.some((option) => option.row_status === "booked" && option.airline);
  const lodgingBooked = options.some((option) => option.row_status === "booked" && option.name);
  const workspaceRows = state.trip?.workspace?.tabs || [];
  const hasConfirmation = JSON.stringify(workspaceRows).toLowerCase().includes("confirmation");
  return flightBooked && lodgingBooked && hasConfirmation ? "done" : "todo";
}

function bookingMilestoneDetail() {
  return bookingMilestoneState() === "done" ? "confirmed" : "confirmations needed";
}

function renderTripList() {
  const trips = collectTrips();
  const list = document.getElementById("tripList");
  if (!trips.length) {
    list.innerHTML = `<div class="empty-state">No trip state yet.</div>`;
    return;
  }
  list.innerHTML = trips
    .map((trip) => {
      const active = trip.trip_id === state.activeTripId ? " active" : "";
      const menuOpen = trip.trip_id === state.openTripMenuId ? " is-open" : "";
      const title = trip.name || trip.trip_name || trip.trip_id;
      const destination = trip.destination || (trip.destination_seeds || []).join(", ") || trip.status || "";
      return `<div class="trip-list-item${active}">
        <button class="trip-button" type="button" data-trip-id="${escapeHtml(trip.trip_id)}">
          ${escapeHtml(title)}
          <small>${escapeHtml(destination)}</small>
        </button>
        <div class="trip-menu-wrap">
          <button class="trip-menu-button" type="button" data-trip-menu="${escapeHtml(trip.trip_id)}" aria-label="Actions for ${escapeHtml(title)}">...</button>
          <div class="trip-menu${menuOpen}" role="menu">
            <button class="danger-menu-item" type="button" data-delete-trip="${escapeHtml(trip.trip_id)}" role="menuitem">Delete trip</button>
          </div>
        </div>
      </div>`;
    })
    .join("");
  list.querySelectorAll("button[data-trip-id]").forEach((button) => {
    button.addEventListener("click", () => loadTrip(button.dataset.tripId, { gotoNext: true }));
  });
  list.querySelectorAll("button[data-trip-menu]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      state.openTripMenuId = state.openTripMenuId === button.dataset.tripMenu ? null : button.dataset.tripMenu;
      renderTripList();
    });
  });
  list.querySelectorAll("button[data-delete-trip]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteTrip(button.dataset.deleteTrip);
    });
  });
}

async function deleteTrip(tripId) {
  state.openTripMenuId = null;
  const confirmed = window.confirm(
    `Delete ${tripId} from local Trippy planning state? This removes intake, draft, workspace, shortlists, canonical trip, and local map exports. Learning logs stay as audit history.`,
  );
  if (!confirmed) {
    return;
  }
  await apiPost("/api/delete-trip", { trip_id: tripId });
  if (state.activeTripId === tripId) {
    state.activeTripId = null;
    state.trip = null;
    state.activeStage = "intake";
  }
  await refresh();
}

function renderStageTabs() {
  const tabs = document.getElementById("stageTabs");
  if (!tabs) {
    return;
  }
  tabs.innerHTML = "";
}

function wireProgressBar() {
  document.querySelectorAll("[data-progress-stage]").forEach((button) => {
    button.addEventListener("click", () => {
      const stage = button.dataset.progressStage;
      if (stage && isStageUnlocked(stage)) {
        state.activeStage = stage;
        render();
        document.querySelector(".wizard-panel")?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      }
    });
  });
}

function progressStep(item) {
  const title = `${item.label}: ${item.detail}`;
  return `<button type="button" class="progress-step ${escapeHtml(item.state)}" data-progress-stage="${escapeHtml(progressStageForMilestone(item.key))}" title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}" data-tooltip="${escapeHtml(title)}">
    <span class="progress-icon" aria-hidden="true">${progressIcon(item.key)}</span>
    <span class="sr-only">${escapeHtml(title)}</span>
  </button>`;
}

function progressIcon(key) {
  const icons = {
    intake: `<svg viewBox="0 0 24 24" role="img"><path d="M8 4h8l1 2h3v15H4V6h3l1-2Z"/><path d="M8 10h8M8 14h8M8 18h5"/></svg>`,
    shape: `<svg viewBox="0 0 24 24" role="img"><path d="M5 19V5l5 3 5-3 4 3v14l-4-3-5 3-5-3Z"/><path d="M10 8v14M15 5v14"/></svg>`,
    flights: `<svg viewBox="0 0 24 24" role="img"><path d="M3 13 21 5l-5 16-4-7-6 4 3-6-6 1Z"/></svg>`,
    lodging: `<svg viewBox="0 0 24 24" role="img"><path d="M4 11h16v8M4 19V6M20 19v-5H8"/><path d="M8 11V8h5v3"/></svg>`,
    cars: `<svg viewBox="0 0 24 24" role="img"><path d="M5 16h14l-1-5-2-3H8l-2 3-1 5Z"/><path d="M7 16v2M17 16v2M7 12h10"/></svg>`,
    activities: `<svg viewBox="0 0 24 24" role="img"><path d="m12 3 2.4 5 5.6.8-4 3.9.9 5.5L12 15.6 7.1 18.2l.9-5.5-4-3.9 5.6-.8L12 3Z"/></svg>`,
    workspace: `<svg viewBox="0 0 24 24" role="img"><path d="M6 3h9l3 3v15H6V3Z"/><path d="M14 3v4h4M9 11h6M9 15h6M9 19h4"/></svg>`,
    booked: `<svg viewBox="0 0 24 24" role="img"><path d="M20 7 10 17l-5-5"/></svg>`,
  };
  return icons[key] || icons.intake;
}

function progressStageForMilestone(key) {
  const map = {
    intake: "intake",
    shape: "options",
    flights: "flights",
    lodging: "lodging",
    cars: "activities",
    activities: "activities",
    workspace: "plan",
    booked: "plan",
  };
  return map[key] || "start";
}

function renderStage() {
  const body = document.getElementById("stageBody");
  if (state.activeStage === "start") {
    body.innerHTML = startStage();
    wireStartStage(body);
  } else if (state.activeStage === "intake") {
    body.innerHTML = intakeStage();
    wireIntakeStage(body);
  } else if (state.activeStage === "options") {
    body.innerHTML = draftStage();
    wireDraftStage(body);
  } else if (state.activeStage === "flights") {
    body.innerHTML = flightsStage();
    wireFlightsStage(body);
  } else if (state.activeStage === "lodging") {
    body.innerHTML = lodgingStage();
    wireLodgingStage(body);
  } else if (state.activeStage === "activities") {
    body.innerHTML = activitiesStage();
    wireActivitiesStage(body);
  } else if (state.activeStage === "plan") {
    body.innerHTML = planStage();
    wirePlanStage(body);
  } else {
    body.innerHTML = learningStage();
    wireFeedbackForms(body, "review");
  }
}

function startStage() {
  const concepts = state.ideaComparison?.concepts || [];
  return `
    <section class="start-screen">
      <div class="start-hero">
        <p class="eyebrow">Start here</p>
        <h3>Choose how Trippy should begin.</h3>
        <p>Generate is for inspiration. New is for a trip you already have in mind. Nothing is saved until you approve the detailed intake.</p>
      </div>
      <div class="idea-action-grid">
        <article class="idea-action-card suggest">
          <p class="eyebrow">Path A</p>
          <h3>Generate ideas</h3>
          <p>Answer a few lightweight questions and Trippy will suggest a few trip concepts to choose from.</p>
          <button id="ideaSuggestToggle" type="button">${state.showSuggestForm ? "Hide generator" : "Generate"}</button>
        </article>
        <article class="idea-action-card">
          <p class="eyebrow">Path B</p>
          <h3>New trip</h3>
          <p>Open the full intake when you already know the destination, dates, or constraints.</p>
          <button id="ideaNewTrip" type="button">New</button>
        </article>
      </div>
      ${state.showSuggestForm ? suggestIdeaForm() : ""}
      ${
        concepts.length
          ? `<div class="suggestion-grid">${concepts.map(suggestionCard).join("")}</div>`
          : `<div class="empty-state">No generated ideas yet. Use Generate for lightweight ideation, or New for direct planning.</div>`
      }
    </section>
  `;
}

function intakeStage() {
  const intake = state.trip?.intake || state.suggestedIntake || {};
  const party = intake.party || {};
  const selectedParty = party.party_type || "whole_family";
  const isPrefilledSuggestion = !state.trip?.intake && Boolean(state.suggestedIntake);
  return `
    <form id="intakeForm" class="stage-card progressive-form">
      ${state.activeTripId ? `<input type="hidden" name="trip_id" value="${escapeHtml(state.activeTripId)}"><input type="hidden" name="overwrite" value="true">` : ""}
      ${isPrefilledSuggestion ? `<div class="suggestion-prefill"><strong>Suggested starting point.</strong><span>Edit anything here before saving; Trippy has not created the trip yet.</span></div>` : ""}
      <section class="form-section">
        <div>
          <p class="eyebrow">Step 1</p>
          <h3>Trip shape</h3>
        </div>
        <div class="form-grid">
          ${input("trip_name", "Trip name", intake.trip_name || "New Trip")}
          ${input("destinations", "Destination", (intake.destination_seeds || []).join(", "))}
          ${input("travel_window", "Travel window", intake.travel_window?.label || "Flexible")}
          ${input("season", "Season", intake.travel_window?.season || "")}
          ${input("duration", "Duration", intake.duration_label || intake.duration_days || "6 to 8 days")}
          ${input("departure_airports", "Departure", (intake.departure_airports || ["YYZ"]).join(", "))}
        </div>
      </section>

      <section class="form-section">
        <div>
          <p class="eyebrow">Step 2</p>
          <h3>Who is going</h3>
        </div>
        <div class="form-grid">
          ${select("party_type", "Party type", selectedParty, partyOptions)}
          ${input("travelers", "Travelers", party.total_travelers || intake.travelers || 5, "number")}
          ${input("adults", "Adults", party.adults ?? 2, "number")}
          ${input("children", "Children", party.children ?? 3, "number", 'data-party-scope="kids family"')}
          ${input("child_ages", "Child ages", (party.child_ages || [16, 14, 11]).join(", "), "text", 'data-party-scope="kids family"')}
          ${textarea("roster", "Roster", rosterText(party), "Ken|adult, Sue|adult, Child 1|16, Child 2|14, Child 3|11")}
        </div>
      </section>

      <section class="form-section">
        <div>
          <p class="eyebrow">Step 3</p>
          <h3>Priorities</h3>
        </div>
        <div class="form-grid">
          ${input("budget_cad", "Budget CAD", intake.budget_cad || "", "number")}
          ${input("max_travel_time_hours", "Max travel hours", intake.max_travel_time_hours || "", "number")}
          ${select("pace", "Pace", intake.pace || "balanced", ["relaxed", "balanced", "active"])}
          ${select("crowd_tolerance", "Crowds", intake.crowd_tolerance || "low", ["low", "medium", "high"])}
          ${select("food_priority", "Food priority", intake.food_priority || "high", ["low", "medium", "high"])}
          ${textarea("goals", "Goals", (intake.goals || []).join(", "))}
          ${textarea("avoidances", "Avoid", (intake.avoidances || ["huge crowds", "stressful transfers"]).join(", "))}
        </div>
      </section>

      <section class="form-section">
        <div>
          <p class="eyebrow">Step 4</p>
          <h3>Comfort details</h3>
        </div>
        <div class="form-grid">
          ${textarea("sleeping_considerations", "Family sleeping", party.sleeping_considerations || "At least 3 beds; king strongly preferred for adults", "", 'data-party-scope="family"')}
          ${textarea("privacy_needs", "Family privacy", party.privacy_needs || "Parents need real privacy where practical", "", 'data-party-scope="family adults_multi"')}
          ${textarea("mobility_notes", "Mobility / stamina", party.mobility_notes || "Avoid exhausting transfer days")}
          ${textarea("child_friendliness_notes", "Child fit", party.child_friendliness_notes || "Activities should work for active teens and one younger child", "", 'data-party-scope="kids family"')}
          ${textarea("lodging_notes", "Lodging", intake.lodging_preferences?.notes || "comfortable, safe, practical location")}
          ${textarea("car_rental", "Cars", intake.car_rental_expectations?.notes || "decide based on local driving, parking, and luggage fit")}
          ${textarea("notes", "Notes", intake.freeform_notes || "")}
        </div>
        <label class="check-row"><input type="checkbox" name="prefer_direct" ${intake.flight_preferences?.prefer_direct !== false ? "checked" : ""}> Prefer direct flights</label>
        <label class="check-row" data-party-scope="family adults_multi"><input type="checkbox" name="separate_rooms_preferred" ${party.separate_rooms_preferred ? "checked" : ""}> Separate rooms/privacy matter</label>
      </section>

      <div class="button-row">
        <button type="submit">Save intake</button>
        <button type="button" class="secondary" id="draftFromIntake">Save and build options</button>
      </div>
      <p class="inline-result"></p>
    </form>
    ${feedbackBlock("intake")}
  `;
}

function draftStage() {
  const draft = state.trip?.draft;
  if (!state.activeTripId) {
    return `<div class="empty-state">Create or select a trip first.</div>`;
  }
  const options = draft?.options || [];
  const buttonLabel = options.length ? "Refresh from intake" : "Build options";
  return `
    <div class="stage-card action-card">
      <div>
        <h3>${options.length ? "Planning shapes are deterministic from the saved intake" : "Build planning shapes"}</h3>
        <p>${options.length ? "Refresh only after changing constraints. Choosing one shape moves directly into flights." : "Trippy will build a small set of planning shapes from the saved intake."}</p>
      </div>
      <button id="draftButton" type="button">${buttonLabel}</button>
      <p class="inline-result"></p>
    </div>
    <div class="option-grid">
      ${options.length ? options.map(planOptionCard).join("") : `<div class="empty-state">No options yet.</div>`}
    </div>
    ${feedbackBlock("draft")}
  `;
}

function researchStage() {
  if (!state.activeTripId) {
    return `<div class="empty-state">Create or select a trip first.</div>`;
  }
  return `
    <div class="stage-card action-card">
      <div>
        <h3>Exact research</h3>
        <p>Refresh source-backed shortlists, then compare timing, cost bands, roster fit, and friction.</p>
      </div>
      <div class="button-row compact-buttons">
        <button data-shortlist="flights" data-auto-research="true" type="button">Flights</button>
        <button data-shortlist="lodging" data-auto-research="true" type="button">Lodging</button>
        <button data-shortlist="cars" type="button">Cars</button>
        <button data-shortlist="activities" type="button">Activities</button>
      </div>
      <p class="inline-result"></p>
    </div>
    ${flightCandidateForm()}
    ${lodgingCandidateForm()}
    <div class="research-stack">${shortlistCards()}</div>
    ${feedbackBlock("research")}
  `;
}

function flightCandidateForm() {
  return `<form id="flightCandidateForm" class="stage-card candidate-form flight-candidate-form">
    <div>
      <p class="eyebrow">Bring your own flight</p>
      <h3>Add flight candidate</h3>
      <p>Paste a Google Flights, Kayak, Expedia, Flighthub link, or itinerary text. Trippy will choose the best available research path and score timing, layovers, fare confidence, and friction.</p>
    </div>
    <div class="form-grid">
      ${input("name", "Airline / label", "", "text")}
      ${input("link", "Link", "", "url")}
      ${textarea("notes", "Flight notes", "", "Example: Air Canada AC123 + TAP TP1861, depart 9:15 PM, arrive 2:20 PM, duration 10h 35m, 1 stop via LIS, layover 2h 20m, CAD 1180 pp, checked bag included.")}
    </div>
    <div class="button-row">
      <button type="submit">Evaluate flight</button>
    </div>
    <p class="inline-result"></p>
  </form>`;
}

function lodgingCandidateForm() {
  return `<form id="lodgingCandidateForm" class="stage-card candidate-form">
    <div>
      <p class="eyebrow">Bring your own option</p>
      <h3>Add lodging candidate</h3>
      <p>Paste a Booking.com, Airbnb, VRBO, hotel, or notes-only candidate. Trippy will choose the best available research path and score it in the same lodging model.</p>
    </div>
    <div class="form-grid">
      ${input("name", "Name", "", "text")}
      ${input("link", "Link", "", "url")}
      ${textarea("notes", "Notes", "", "Paste bed layout, area, nightly/total cost, parking, cancellation, or why you like it.")}
    </div>
    <div class="button-row">
      <button type="submit">Evaluate lodging</button>
    </div>
    <p class="inline-result"></p>
  </form>`;
}

function flightsStage() {
  if (!state.activeTripId) {
    return `<div class="empty-state">Create or select a trip first.</div>`;
  }
  const shortlist = shortlistByCategory("flights");
  return `
    <div class="guided-step-layout">
      <section class="stage-card action-card">
        <div>
          <p class="eyebrow">Step 4</p>
          <h3>Find the best flight fit</h3>
          <p>Compare timing, route pain, price bands, and source confidence. Trippy recommends the lowest-friction option from current evidence.</p>
          ${truthLegend()}
        </div>
        <div class="button-row compact-buttons">
          <button data-shortlist="flights" data-auto-research="true" type="button">${shortlist ? "Refresh flights" : "Find flights"}</button>
        </div>
        <p class="inline-result"></p>
      </section>
      ${shortlist ? flightComparison(shortlist) : `<div class="empty-state">Flight suggestions appear here after you choose a trip shape.</div>`}
      <details class="stage-card quiet-details">
        <summary>Add a flight you found</summary>
        ${flightCandidateForm()}
      </details>
      <div class="button-row step-forward-row">
        <button type="button" class="secondary" data-next-stage="options">Back to options</button>
        <button type="button" data-next-stage="lodging">Next: lodging</button>
      </div>
    </div>
    ${feedbackBlock("flights")}
  `;
}

function lodgingStage() {
  if (!state.activeTripId) {
    return `<div class="empty-state">Create or select a trip first.</div>`;
  }
  const shortlist = shortlistByCategory("lodging");
  return `
    <div class="guided-step-layout">
      <section class="stage-card action-card">
        <div>
          <p class="eyebrow">Step 5</p>
          <h3>Choose the stay structure</h3>
          <p>Trippy checks whether one base or split stays better matches the chosen trip shape, then compares properties against party fit.</p>
          ${truthLegend()}
        </div>
        <div class="button-row compact-buttons">
          <button data-shortlist="lodging" data-auto-research="true" type="button">${shortlist ? "Refresh lodging" : "Find lodging"}</button>
        </div>
        <p class="inline-result"></p>
      </section>
      ${lodgingStructurePanel(shortlist)}
      ${shortlist ? lodgingComparison(shortlist) : `<div class="empty-state">Lodging suggestions appear here after the selected shape is known.</div>`}
      <details class="stage-card quiet-details">
        <summary>Add a hotel, Airbnb, or VRBO you found</summary>
        ${lodgingCandidateForm()}
      </details>
      <div class="button-row step-forward-row">
        <button type="button" class="secondary" data-next-stage="flights">Back to flights</button>
        <button type="button" data-next-stage="activities">Next: activities</button>
      </div>
    </div>
    ${feedbackBlock("lodging")}
  `;
}

function activitiesStage() {
  if (!state.activeTripId) {
    return `<div class="empty-state">Create or select a trip first.</div>`;
  }
  const activities = shortlistByCategory("activities");
  const cars = shortlistByCategory("cars");
  return `
    <div class="guided-step-layout">
      <section class="stage-card action-card">
        <div>
          <p class="eyebrow">Step 6</p>
          <h3>Activities and local movement</h3>
          <p>Keep the days balanced: safe, well-reviewed activities, practical driving, and enough downtime.</p>
        </div>
        <div class="button-row compact-buttons">
          <button data-shortlist="activities" type="button">${activities ? "Refresh activities" : "Find activities"}</button>
          <button data-shortlist="cars" type="button">${cars ? "Refresh cars" : "Find cars"}</button>
        </div>
        <p class="inline-result"></p>
      </section>
      <div class="research-stack">
        ${activities ? activitySchedulePanel(activities) : ""}
        ${activities ? activityComparison(activities) : `<div class="empty-state">Activity suggestions are not built yet.</div>`}
        ${cars ? carComparison(cars) : `<div class="empty-state">Car suggestions are not built yet.</div>`}
      </div>
      <div class="button-row step-forward-row">
        <button type="button" class="secondary" data-next-stage="lodging">Back to lodging</button>
        <button type="button" data-next-stage="plan">Next: timeline + map</button>
      </div>
    </div>
    ${feedbackBlock("activities")}
  `;
}

function planStage() {
  if (!state.activeTripId) {
    return `<div class="empty-state">Create or select a trip first.</div>`;
  }
  const workspace = state.trip?.workspace;
  const artifact = state.trip?.map_artifact;
  const mapRows = (workspace?.tabs || []).find((tab) => tab.name === "Maps")?.rows || [];
  const hasGoogleSheet = Boolean(workspace?.google_sheet_id || workspace?.google_sheet_url);
  const sheetButtonLabel = hasGoogleSheet ? "Update Google Sheet" : "Create Google Sheet";
  return `
    <div class="guided-step-layout">
      ${structureGuidancePanel()}
      <section class="stage-card action-card">
        <div>
          <p class="eyebrow">Step 7</p>
          <h3>Google Sheet and custom map</h3>
          <p>Keep the planning sheet, timeline, map anchors, risks, and next actions current.</p>
        </div>
        <div class="button-row compact-buttons">
          <button id="googleWorkspaceButton" type="button">${sheetButtonLabel}</button>
          <button id="mapButton" type="button" class="secondary">${artifact ? "Update custom map" : "Create custom map"}</button>
        </div>
        <p class="inline-result"></p>
      </section>
      ${workspace ? workspaceSummary(workspace) : `<div class="empty-state">Create the Google Sheet to build the Master Timeline, map anchors, and risks.</div>`}
      ${artifact ? embeddedMapPanel(artifact) : fallbackMapPanel(mapRows)}
      <div class="button-row step-forward-row">
        <button type="button" class="secondary" data-next-stage="activities">Back to activities</button>
        <button type="button" data-next-stage="review">Next: feedback</button>
      </div>
    </div>
    ${feedbackBlock("plan")}
  `;
}

function workspaceStage() {
  const workspace = state.trip?.workspace;
  return `
    <div class="stage-card action-card">
      <div>
        <h3>Workspace</h3>
        <p>Hydrate Overview, Master Timeline, Flights, Lodging, Cars, Activities, Maps, and Risks from the selected plan and shortlists.</p>
      </div>
      <button id="workspaceButton" type="button">Prepare workspace</button>
      <p class="inline-result"></p>
    </div>
    ${workspace ? workspaceSummary(workspace) : `<div class="empty-state">No workspace yet.</div>`}
    ${feedbackBlock("workspace")}
  `;
}

function mapsStage() {
  const artifact = state.trip?.map_artifact;
  const workspace = state.trip?.workspace;
  const mapRows = (workspace?.tabs || []).find((tab) => tab.name === "Maps")?.rows || [];
  return `
    <div class="stage-card action-card">
      <div>
        <h3>Planning map</h3>
        <p>One practical map surface for lodging, airport, food, activity, and route sequence checks.</p>
      </div>
      <button id="mapButton" type="button">Build map</button>
      <p class="inline-result"></p>
    </div>
    ${artifact ? embeddedMapPanel(artifact) : fallbackMapPanel(mapRows)}
    ${feedbackBlock("maps")}
  `;
}

function wireStartStage(root) {
  wireIdeaControls(root);
}

function learningStage() {
  const workflows = state.trip?.recent_workflows || [];
  const logs = currentRunLog();
  const proposals = state.trip?.pending_learning_proposals || state.app?.pending_learning_proposals || [];
  return `
    <div class="stage-card">
      <h3>Recent workflow IDs</h3>
      <div class="metric-row">${workflows.map((workflow) => `<span class="metric">${escapeHtml(workflow.workflow_name)} · ${escapeHtml(workflow.id)}</span>`).join("") || `<span class="metric">No workflows yet</span>`}</div>
      <h3>Backend log</h3>
      <p class="log-path">${escapeHtml(currentBackendLogPath() || "No log file yet")}</p>
      <div class="metric-row">
        <span class="metric">${logs.length} visible event(s)</span>
        <span class="metric ${proposals.length ? "warn" : "live"}">${proposals.length} pending proposal(s)</span>
      </div>
    </div>
    <div class="run-log compact">${logs.slice(-8).reverse().map(logRow).join("") || `<div class="empty-state">No learning events yet.</div>`}</div>
    ${feedbackBlock("review")}
  `;
}

function wireIntakeStage(root) {
  const form = root.querySelector("#intakeForm");
  const result = root.querySelector(".inline-result");
  adaptPartyFields(form, false);
  form.querySelector("[name=party_type]").addEventListener("change", () => adaptPartyFields(form, true));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await saveIntake(form, result);
  });
  root.querySelector("#draftFromIntake").addEventListener("click", async () => {
    const response = await saveIntake(form, result);
    if (response?.intake?.trip_id) {
      const draft = await apiPost("/api/draft", { trip_id: response.intake.trip_id });
      state.lastWorkflowByStage.draft = draft.workflow_id;
      state.activeStage = "options";
      await loadTrip(response.intake.trip_id);
      render();
    }
  });
  wireFeedbackForms(root, "intake");
}

function adaptPartyFields(form, resetValues) {
  const partyType = form.querySelector("[name=party_type]").value;
  const isCouple = partyType === "couple";
  const hasKids = ["whole_family", "subset_family", "family_plus_others", "custom"].includes(partyType);
  const isMultiAdult = ["adults_only", "family_plus_others", "custom"].includes(partyType);
  form.querySelectorAll("[data-party-scope]").forEach((element) => {
    const scope = element.dataset.partyScope || "";
    const shouldShow =
      (scope.includes("kids") && hasKids) ||
      (scope.includes("family") && hasKids) ||
      (scope.includes("adults_multi") && isMultiAdult);
    element.classList.toggle("is-hidden", !shouldShow);
  });
  if (resetValues && isCouple) {
    setFormValue(form, "travelers", "2");
    setFormValue(form, "adults", "2");
    setFormValue(form, "children", "0");
    setFormValue(form, "child_ages", "");
    setFormValue(form, "roster", "Ken|adult, Sue|adult");
    setFormValue(form, "sleeping_considerations", "");
    setFormValue(form, "privacy_needs", "");
    setFormValue(form, "child_friendliness_notes", "");
    const separate = form.querySelector("[name=separate_rooms_preferred]");
    if (separate) {
      separate.checked = false;
    }
  } else if (resetValues && hasKids) {
    setFormValue(form, "travelers", "5");
    setFormValue(form, "adults", "2");
    setFormValue(form, "children", "3");
    setFormValue(form, "child_ages", "16, 14, 11");
    setFormValue(form, "roster", "Ken|adult, Jenn|adult, Child 1|16, Child 2|14, Child 3|11");
  } else if (resetValues && partyType === "adults_only") {
    setFormValue(form, "children", "0");
    setFormValue(form, "child_ages", "");
  }
}

function setFormValue(form, name, value) {
  const input = form.querySelector(`[name=${name}]`);
  if (input) {
    input.value = value;
  }
}

async function saveIntake(form, result) {
  try {
    setWorking(result, "Saving intake");
    const payload = formPayload(form);
    const response = await apiPost("/api/intake", payload);
    state.lastWorkflowByStage.intake = response.workflow_id;
    state.activeTripId = response.intake.trip_id;
    state.isCreatingTrip = false;
    state.suggestedIntake = null;
    await loadTrip(response.intake.trip_id);
    result.textContent = `Saved ${response.intake.trip_id}`;
    return response;
  } catch (error) {
    result.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
    return null;
  }
}

function wireDraftStage(root) {
  const button = root.querySelector("#draftButton");
  if (button) {
    button.addEventListener("click", async () => {
      await runStage(root, "draft", "/api/draft", { trip_id: state.activeTripId });
    });
  }
  root.querySelectorAll("[data-select-option]").forEach((selectButton) => {
    selectButton.addEventListener("click", async () => {
      await selectOptionAndStartResearch(root, selectButton.dataset.selectOption);
    });
  });
  wireFeedbackForms(root, "draft");
}

async function selectOptionAndStartResearch(root, optionId) {
  const result = root.querySelector(".inline-result");
  try {
    setWorking(result, "Selecting option and finding first recommendations");
    const selection = await apiPost("/api/select", {
      trip_id: state.activeTripId,
      option_id: optionId,
    });
    state.lastWorkflowByStage.draft = selection.workflow_id;
    for (const category of ["flights", "lodging", "cars", "activities"]) {
      result.textContent = `Building ${category} suggestions...`;
      const response = await apiPost("/api/shortlist", {
        trip_id: state.activeTripId,
        category,
        validate_live: false,
      });
      state.lastWorkflowByStage[category] = response.workflow_id;
    }
    state.activeStage = "flights";
    await loadTrip(state.activeTripId);
    render();
  } catch (error) {
    result.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
  }
}

function wireResearchStage(root) {
  const flightSort = root.querySelector("#flightSort");
  if (flightSort) {
    flightSort.addEventListener("change", () => {
      state.flightSort = flightSort.value;
      render();
    });
  }
  root.querySelectorAll("[data-shortlist]").forEach((button) => {
    button.addEventListener("click", async () => {
      await runStage(root, "research", "/api/shortlist", {
        trip_id: state.activeTripId,
        category: button.dataset.shortlist,
        validate_live: button.dataset.autoResearch === "true",
        deep_research: button.dataset.autoResearch === "true" || button.dataset.deepResearch === "true",
        adapter: "auto",
      });
    });
  });
  const candidate = root.querySelector("#lodgingCandidateForm");
  if (candidate) {
    candidate.addEventListener("submit", async (event) => {
      event.preventDefault();
      const result = candidate.querySelector(".inline-result");
      try {
        setWorking(result, "Evaluating lodging candidate");
        const payload = formPayload(candidate);
        payload.trip_id = state.activeTripId;
        payload.validate_live = true;
        payload.deep_research = true;
        payload.adapter = "auto";
        const response = await apiPost("/api/lodging-candidate", payload);
        state.lastWorkflowByStage.research = response.workflow_id;
        await loadTrip(state.activeTripId);
        state.activeStage = "research";
        render();
      } catch (error) {
        result.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
      }
    });
  }
  const flightCandidate = root.querySelector("#flightCandidateForm");
  if (flightCandidate) {
    flightCandidate.addEventListener("submit", async (event) => {
      event.preventDefault();
      const result = flightCandidate.querySelector(".inline-result");
      try {
        setWorking(result, "Evaluating flight candidate");
        const payload = formPayload(flightCandidate);
        payload.trip_id = state.activeTripId;
        payload.validate_live = true;
        payload.deep_research = true;
        payload.adapter = "auto";
        const response = await apiPost("/api/flight-candidate", payload);
        state.lastWorkflowByStage.research = response.workflow_id;
        await loadTrip(state.activeTripId);
        state.activeStage = "research";
        render();
      } catch (error) {
        result.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
      }
    });
  }
  root.querySelectorAll("[data-select-flight]").forEach((button) => {
    button.addEventListener("click", async () => {
      const result = root.querySelector(".inline-result");
      try {
        setWorking(result, "Selecting flight and updating planning timeline");
        const response = await apiPost("/api/select-flight", {
          trip_id: state.activeTripId,
          option_id: button.dataset.selectFlight,
        });
        state.lastWorkflowByStage.research = response.workflow_id;
        await loadTrip(state.activeTripId);
        state.activeStage = "workspace";
        render();
      } catch (error) {
        result.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
      }
    });
  });
  wireFeedbackForms(root, "research");
}

function wireFlightsStage(root) {
  wireShortlistButtons(root, "flights");
  const flightSort = root.querySelector("#flightSort");
  if (flightSort) {
    flightSort.addEventListener("change", () => {
      state.flightSort = flightSort.value;
      render();
    });
  }
  const flightCandidate = root.querySelector("#flightCandidateForm");
  if (flightCandidate) {
    flightCandidate.addEventListener("submit", async (event) => {
      event.preventDefault();
      const result = flightCandidate.querySelector(".inline-result");
      try {
        setWorking(result, "Evaluating flight candidate");
        const payload = formPayload(flightCandidate);
        payload.trip_id = state.activeTripId;
        payload.validate_live = true;
        payload.deep_research = true;
        payload.adapter = "auto";
        const response = await apiPost("/api/flight-candidate", payload);
        state.lastWorkflowByStage.flights = response.workflow_id;
        await loadTrip(state.activeTripId);
        state.activeStage = "flights";
        render();
      } catch (error) {
        result.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
      }
    });
  }
  root.querySelectorAll("[data-select-flight]").forEach((button) => {
    button.addEventListener("click", async () => {
      const result = root.querySelector(".inline-result");
      try {
        setWorking(result, "Selecting flight and updating timing guidance");
        const response = await apiPost("/api/select-flight", {
          trip_id: state.activeTripId,
          option_id: button.dataset.selectFlight,
        });
        state.lastWorkflowByStage.flights = response.workflow_id;
        await loadTrip(state.activeTripId);
        state.activeStage = "lodging";
        render();
      } catch (error) {
        result.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
      }
    });
  });
  wireStageNavigation(root);
  wireFeedbackForms(root, "flights");
}

function wireLodgingStage(root) {
  wireShortlistButtons(root, "lodging");
  const structureForm = root.querySelector("#stayStructureForm");
  if (structureForm) {
    structureForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const result = structureForm.querySelector(".inline-result");
      try {
        setWorking(result, "Saving stay structure");
        const payload = formPayload(structureForm);
        const response = await apiPost("/api/lodging-structure", {
          trip_id: state.activeTripId,
          strategy: payload.strategy,
          night_plan: parseNightPlanText(payload.night_plan_text),
          notes: payload.notes || "",
        });
        state.lastWorkflowByStage.lodging = response.workflow_id;
        await loadTrip(state.activeTripId);
        state.activeStage = "lodging";
        render();
      } catch (error) {
        result.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
      }
    });
  }
  const candidate = root.querySelector("#lodgingCandidateForm");
  if (candidate) {
    candidate.addEventListener("submit", async (event) => {
      event.preventDefault();
      const result = candidate.querySelector(".inline-result");
      try {
        setWorking(result, "Evaluating lodging candidate");
        const payload = formPayload(candidate);
        payload.trip_id = state.activeTripId;
        payload.validate_live = true;
        payload.deep_research = true;
        payload.adapter = "auto";
        const response = await apiPost("/api/lodging-candidate", payload);
        state.lastWorkflowByStage.lodging = response.workflow_id;
        await loadTrip(state.activeTripId);
        state.activeStage = "lodging";
        render();
      } catch (error) {
        result.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
      }
    });
  }
  root.querySelectorAll("[data-select-lodging]").forEach((button) => {
    button.addEventListener("click", async () => {
      const result = root.querySelector(".inline-result");
      try {
        setWorking(result, "Selecting lodging");
        const response = await apiPost("/api/select-lodging", {
          trip_id: state.activeTripId,
          option_id: button.dataset.selectLodging,
        });
        state.lastWorkflowByStage.lodging = response.workflow_id;
        await loadTrip(state.activeTripId);
        state.activeStage = "lodging";
        render();
      } catch (error) {
        result.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
      }
    });
  });
  wireStageNavigation(root);
  wireFeedbackForms(root, "lodging");
}

function wireActivitiesStage(root) {
  wireShortlistButtons(root, "activities");
  root.querySelectorAll("[data-select-car]").forEach((button) => {
    button.addEventListener("click", async () => {
      const result = root.querySelector(".inline-result");
      try {
        setWorking(result, "Selecting car and updating local movement plan");
        const response = await apiPost("/api/select-car", {
          trip_id: state.activeTripId,
          option_id: button.dataset.selectCar,
        });
        state.lastWorkflowByStage.activities = response.workflow_id;
        await loadTrip(state.activeTripId);
        state.activeStage = "activities";
        render();
      } catch (error) {
        result.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
      }
    });
  });
  root.querySelectorAll("[data-select-activity]").forEach((button) => {
    button.addEventListener("click", async () => {
      const result = root.querySelector(".inline-result");
      try {
        setWorking(result, "Approving activity and adding it to the timeline");
        const response = await apiPost("/api/select-activity", {
          trip_id: state.activeTripId,
          option_id: button.dataset.selectActivity,
        });
        state.lastWorkflowByStage.activities = response.workflow_id;
        await loadTrip(state.activeTripId);
        state.activeStage = "activities";
        render();
      } catch (error) {
        result.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
      }
    });
  });
  root.querySelectorAll("[data-activity-schedule-form]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const result = root.querySelector(".inline-result");
      const payload = formPayload(form);
      try {
        setWorking(result, "Saving activity schedule");
        const response = await apiPost("/api/schedule-activity", {
          trip_id: state.activeTripId,
          option_id: payload.option_id,
          day: Number(payload.day || 0) || null,
          date: payload.date || "",
          start_time: payload.start_time || "",
          end_time: payload.end_time || "",
          fixed: payload.fixed === "on",
          notes: payload.notes || "",
        });
        state.lastWorkflowByStage.activities = response.workflow_id;
        await loadTrip(state.activeTripId);
        state.activeStage = "activities";
        render();
      } catch (error) {
        result.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
      }
    });
  });
  wireStageNavigation(root);
  wireFeedbackForms(root, "activities");
}

function wirePlanStage(root) {
  const googleWorkspaceButton = root.querySelector("#googleWorkspaceButton");
  if (googleWorkspaceButton) {
    googleWorkspaceButton.addEventListener("click", async () => {
      await runStage(root, "plan", "/api/workspace", {
        trip_id: state.activeTripId,
        validate_live: true,
        create_google_sheet: true,
      });
      state.activeStage = "plan";
      render();
    });
  }
  const mapButton = root.querySelector("#mapButton");
  if (mapButton) {
    mapButton.addEventListener("click", async () => {
      await runStage(root, "plan", "/api/map", { trip_id: state.activeTripId });
      state.activeStage = "plan";
      render();
    });
  }
  wireStageNavigation(root);
  wireFeedbackForms(root, "plan");
}

function wireShortlistButtons(root, stage) {
  root.querySelectorAll("[data-shortlist]").forEach((button) => {
    button.addEventListener("click", async () => {
      const category = button.dataset.shortlist;
      const autoResearch = button.dataset.autoResearch === "true";
      await runStage(root, stage, "/api/shortlist", {
        trip_id: state.activeTripId,
        category,
        validate_live: autoResearch,
        deep_research: autoResearch || button.dataset.deepResearch === "true",
        adapter: "auto",
      });
      state.activeStage = stage;
      render();
    });
  });
}

function wireStageNavigation(root) {
  root.querySelectorAll("[data-next-stage]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeStage = button.dataset.nextStage;
      render();
      document.getElementById("stageBody")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
}

function wireWorkspaceStage(root) {
  const button = root.querySelector("#workspaceButton");
  if (button) {
    button.addEventListener("click", async () => {
      await runStage(root, "workspace", "/api/workspace", {
        trip_id: state.activeTripId,
        validate_live: true,
        create_google_sheet: false,
      });
    });
  }
  wireFeedbackForms(root, "workspace");
}

function wireMapsStage(root) {
  const button = root.querySelector("#mapButton");
  if (button) {
    button.addEventListener("click", async () => {
      await runStage(root, "maps", "/api/map", { trip_id: state.activeTripId });
    });
  }
  wireFeedbackForms(root, "maps");
}

async function runStage(root, stage, path, payload) {
  const result = root.querySelector(".inline-result");
  try {
    setWorking(result, "Working");
    const response = await apiPost(path, payload);
    state.lastWorkflowByStage[stage] = response.workflow_id;
    await loadTrip(state.activeTripId);
    result.textContent = response.next_step || "Done";
  } catch (error) {
    result.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
  }
}

function wireFeedbackForms(root, stage) {
  root.querySelectorAll(".feedback-form").forEach((form) => {
    const workflowInput = form.querySelector("[name=workflow_id]");
    workflowInput.value = state.lastWorkflowByStage[stage] || latestWorkflowId() || "";
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const result = form.querySelector(".feedback-result");
      try {
        setWorking(result, "Sending feedback");
        const payload = formPayload(form);
        const response = await apiPost("/api/feedback", payload);
        const proposalCount = response.learning_proposals.length;
        result.textContent = proposalCount
          ? `${proposalCount} review proposal(s) created. ${response.next_step}`
          : response.next_step;
        await refresh();
      } catch (error) {
        result.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
      }
    });
  });
}

function feedbackBlock(stage) {
  const workflowId = state.lastWorkflowByStage[stage] || latestWorkflowId() || "";
  const template = document.getElementById("feedbackTemplate");
  const fragment = template.innerHTML.replace(
    'name="workflow_id"',
    `name="workflow_id" value="${escapeHtml(workflowId)}"`,
  );
  return `<div class="stage-card"><h3>Feedback</h3>${fragment}</div>`;
}

function renderPicks() {
  const picks = recommendedOptions();
  document.getElementById("pickCount").textContent = `${picks.length} ready`;
  document.getElementById("pickGrid").innerHTML = picks.length
    ? picks.map(pickCard).join("")
    : `<div class="empty-state">Select a plan or generate shortlists to see current picks.</div>`;
}

function renderRunLog() {
  const logs = currentRunLog();
  document.getElementById("logCount").textContent = `${logs.length} events`;
  document.getElementById("backendLogPath").textContent = currentBackendLogPath()
    ? `Backend JSONL: ${currentBackendLogPath()}`
    : "Backend JSONL will appear after the first workflow event.";
  document.getElementById("runLog").innerHTML = logs.length
    ? logs.slice().reverse().map(logRow).join("")
    : `<div class="empty-state">Run a stage or send feedback to populate the log.</div>`;
}

function renderIdeas() {
  if (!document.getElementById("ideaGrid")) {
    return;
  }
  const concepts = state.ideaComparison?.concepts || [];
  document.getElementById("ideaCount").textContent = concepts.length
    ? `${concepts.length} suggestion(s)`
    : "New or suggest";
  const body = document.getElementById("ideaGrid");
  body.innerHTML = `
    <div class="idea-action-grid">
      <article class="idea-action-card">
        <p class="eyebrow">Detailed path</p>
        <h3>New trip</h3>
        <p>Open the full intake form when you already know the destination or want to control the details yourself.</p>
        <button id="ideaNewTrip" type="button">New</button>
      </article>
      <article class="idea-action-card suggest">
        <p class="eyebrow">Quick inspiration</p>
        <h3>Suggest a trip</h3>
        <p>Tell Trippy who is going, when, and the basic vibe. Pick a suggestion to pre-fill the detailed form.</p>
        <button id="ideaSuggestToggle" type="button">${state.showSuggestForm ? "Hide suggest" : "Suggest"}</button>
      </article>
    </div>
    ${state.showSuggestForm ? suggestIdeaForm() : ""}
    ${
      concepts.length
        ? `<div class="suggestion-grid">${concepts.map(suggestionCard).join("")}</div>`
        : `<div class="empty-state">No hard-coded bucket here. Use New for the full form or Suggest for constraint-based ideas.</div>`
    }
  `;
  wireIdeaControls(body);
}

function suggestIdeaForm() {
  const request = state.ideaRequest || {};
  const partyType = request.party_type || "whole_family";
  return `<form id="ideaSuggestForm" class="stage-card suggest-form">
    <div>
      <p class="eyebrow">Fast suggest</p>
      <h3>Who, when, and what kind of trip?</h3>
      <p>Trippy will rank concept options from priors and constraints. These are not live-priced until the later flight and lodging steps.</p>
    </div>
    <div class="form-grid">
      ${select("party_type", "Who is going", partyType, partyOptions)}
      ${input("travelers", "Travelers", request.travelers || (partyType === "couple" ? 2 : 5), "number")}
      ${input("adults", "Adults", request.adults || (partyType === "couple" ? 2 : 2), "number")}
      ${input("children", "Children", request.children || (partyType === "couple" ? 0 : 3), "number", 'data-suggest-scope="kids"')}
      ${input("child_ages", "Child ages", request.child_ages || (partyType === "couple" ? "" : "16, 14, 11"), "text", 'data-suggest-scope="kids"')}
      ${input("time_of_year", "Time of year", request.time_of_year || "", "text")}
      ${input("duration_days", "Ideal days", request.duration_days || "", "number")}
      ${input("max_flight_hours", "Max flight hours", request.max_flight_hours || "", "number")}
      ${input("budget_cad", "Budget CAD", request.budget_cad || "", "number")}
      ${select("activity_level", "Pace", request.activity_level || "balanced", ["relaxed", "balanced", "active"])}
      ${textarea("goals", "Basic desires", request.goals || "great food, low friction, memorable scenery")}
      ${textarea("avoidances", "Avoid", request.avoidances || "huge crowds, stressful transfers")}
    </div>
    <label class="check-row"><input type="checkbox" name="direct_flight_preferred" ${request.direct_flight_preferred !== false ? "checked" : ""}> Prefer direct flights where practical</label>
    <div class="button-row">
      <button type="submit">Suggest trip ideas</button>
    </div>
    <p class="inline-result"></p>
  </form>`;
}

function wireIdeaControls(root) {
  root.querySelector("#ideaNewTrip")?.addEventListener("click", () => startNewTrip());
  root.querySelector("#ideaSuggestToggle")?.addEventListener("click", () => {
    state.showSuggestForm = !state.showSuggestForm;
    render();
  });
  const form = root.querySelector("#ideaSuggestForm");
  if (form) {
    adaptSuggestPartyFields(form, false);
    form.querySelector("[name=party_type]")?.addEventListener("change", () => adaptSuggestPartyFields(form, true));
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const result = form.querySelector(".inline-result");
      try {
        setWorking(result, "Building suggestions");
        const payload = formPayload(form);
        const response = await apiPost("/api/suggest-ideas", payload);
        state.ideaRequest = response.comparison?.request || payload;
        state.ideaComparison = response.comparison;
        state.ideaWorkflowId = response.workflow_id;
        state.lastWorkflowByStage.intake = response.workflow_id;
        state.app = await apiGet("/api/state");
        render();
      } catch (error) {
        result.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
      }
    });
  }
  root.querySelectorAll("[data-use-suggestion]").forEach((button) => {
    button.addEventListener("click", () => {
      const concept = (state.ideaComparison?.concepts || []).find(
        (item) => item.concept_id === button.dataset.useSuggestion,
      );
      if (concept) {
        startNewTrip(prefillIntakeFromIdea(concept, state.ideaRequest || state.ideaComparison?.request || {}));
      }
    });
  });
  root.querySelectorAll("[data-idea-feedback]").forEach((button) => {
    button.addEventListener("click", async () => {
      const concept = (state.ideaComparison?.concepts || []).find(
        (item) => item.concept_id === button.dataset.ideaConcept,
      );
      const feedbackRoot = button.closest(".idea-feedback");
      const result = feedbackRoot?.querySelector(".idea-feedback-result");
      if (!concept || !feedbackRoot || !result) {
        return;
      }
      const notes = feedbackRoot.querySelector("textarea")?.value || "";
      try {
        setWorking(result, "Saving feedback");
        const payload = ideaFeedbackPayload(concept, button.dataset.ideaFeedback, notes);
        const response = await apiPost("/api/feedback", payload);
        state.ideaFeedback[concept.concept_id] = response.feedback;
        result.textContent =
          response.learning_proposals.length > 0
            ? "Feedback saved for review-gated learning."
            : "Feedback saved.";
        state.app = await apiGet("/api/state");
      } catch (error) {
        result.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
      }
    });
  });
}

function adaptSuggestPartyFields(form, resetValues) {
  const partyType = form.querySelector("[name=party_type]").value;
  const hasKids = ["whole_family", "subset_family", "family_plus_others", "custom"].includes(partyType);
  form.querySelectorAll("[data-suggest-scope]").forEach((element) => {
    const scope = element.dataset.suggestScope || "";
    element.classList.toggle("is-hidden", scope.includes("kids") && !hasKids);
  });
  if (!resetValues) {
    return;
  }
  if (partyType === "couple") {
    setFormValue(form, "travelers", "2");
    setFormValue(form, "adults", "2");
    setFormValue(form, "children", "0");
    setFormValue(form, "child_ages", "");
  } else if (partyType === "adults_only") {
    setFormValue(form, "travelers", "2");
    setFormValue(form, "adults", "2");
    setFormValue(form, "children", "0");
    setFormValue(form, "child_ages", "");
  } else if (hasKids) {
    setFormValue(form, "travelers", "5");
    setFormValue(form, "adults", "2");
    setFormValue(form, "children", "3");
    setFormValue(form, "child_ages", "16, 14, 11");
  }
}

function suggestionCard(concept) {
  const destinations = concept.destinations || [];
  const risks = concept.why_it_may_not_fit || concept.major_risks || [];
  const requestedDuration = Number(state.ideaComparison?.request?.duration_days || state.ideaRequest?.duration_days || 0);
  const durationOff = requestedDuration && concept.recommended_duration_days > requestedDuration;
  return `<article class="suggestion-card">
    ${imageBlock(`${destinations.join(" ")} ${concept.title}`, concept.title)}
    <div class="suggestion-body">
      <div class="option-head">
        <h3>${escapeHtml(concept.title)}</h3>
        <span class="metric live">${escapeHtml(concept.total_score)} fit</span>
      </div>
      <p>${escapeHtml(destinations.join(", "))}</p>
      <div class="metric-row">
        <span class="metric ${durationOff ? "warn" : "live"}">${escapeHtml(concept.recommended_duration_days)} days${requestedDuration ? ` for ${escapeHtml(requestedDuration)} requested` : ""}</span>
        <span class="metric">${escapeHtml(concept.best_season)}</span>
        <span class="metric">${escapeHtml(concept.estimated_travel_burden)} travel</span>
      </div>
      <ul class="tight-list">
        ${(concept.rationale || []).slice(0, 2).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
        ${risks.slice(0, 1).map((item) => `<li class="risk">${escapeHtml(item)}</li>`).join("")}
      </ul>
      <button type="button" data-use-suggestion="${escapeHtml(concept.concept_id)}">Use this idea</button>
      ${ideaFeedbackControls(concept)}
    </div>
  </article>`;
}

function ideaFeedbackControls(concept) {
  const saved = state.ideaFeedback[concept.concept_id];
  return `<div class="idea-feedback">
    <label>Feedback on this idea
      <textarea rows="2" placeholder="Example: too long for 6 days, too city-heavy, not enough beach, too expensive">${escapeHtml(saved?.notes || "")}</textarea>
    </label>
    <div class="button-row compact-buttons">
      <button class="mini-button secondary" type="button" data-idea-feedback="too_long" data-idea-concept="${escapeHtml(concept.concept_id)}">Too long</button>
      <button class="mini-button secondary" type="button" data-idea-feedback="not_fit" data-idea-concept="${escapeHtml(concept.concept_id)}">Not a fit</button>
      <button class="mini-button secondary" type="button" data-idea-feedback="helpful" data-idea-concept="${escapeHtml(concept.concept_id)}">Looks good</button>
    </div>
    <small class="idea-feedback-result">${saved ? "Feedback saved." : ""}</small>
  </div>`;
}

function ideaFeedbackPayload(concept, action, notes) {
  const request = state.ideaComparison?.request || state.ideaRequest || {};
  const requestedDuration = request.duration_days || "";
  const workflowId = state.ideaWorkflowId || state.lastWorkflowByStage.intake || latestWorkflowId();
  const base = `Idea "${concept.title}" (${concept.recommended_duration_days} days) from request${requestedDuration ? ` for ${requestedDuration} days` : ""}.`;
  if (action === "helpful") {
    return {
      workflow_id: workflowId,
      rating: "helpful",
      notes: [base, notes || "This idea looks directionally useful."].filter(Boolean).join(" "),
      future_learning: false,
    };
  }
  if (action === "too_long") {
    return {
      workflow_id: workflowId,
      rating: "needs-work",
      notes: [base, notes || "The suggested duration is too long for the requested trip length."].filter(Boolean).join(" "),
      correction: requestedDuration
        ? `Respect the requested ${requestedDuration}-day constraint before ranking ideas. Do not return ${concept.recommended_duration_days}-day concepts unless clearly labeled as outside scope.`
        : "Respect the user's stated duration before ranking ideas.",
      future_learning: true,
    };
  }
  return {
    workflow_id: workflowId,
    rating: "needs-work",
    notes: [base, notes || "This concept is not a good fit."].filter(Boolean).join(" "),
    correction: notes || "Use this rejection to adjust future idea ranking and rationale.",
    future_learning: true,
  };
}

function prefillIntakeFromIdea(concept, request) {
  const party = partyFromIdeaRequest(request);
  const goals = asList(request.goals);
  const avoidances = asList(request.avoidances || request.avoid);
  const duration = request.duration_days || concept.recommended_duration_days;
  const timeOfYear = request.time_of_year || concept.best_season || "Flexible";
  const rationale = (concept.rationale || []).slice(0, 3).join(" ");
  const risks = (concept.why_it_may_not_fit || concept.major_risks || []).slice(0, 2).join(" ");
  return {
    mode: "idea",
    trip_name: concept.title || "Suggested Trip",
    destination_seeds: concept.destinations || [],
    travel_window: {
      label: timeOfYear,
      season: timeOfYear,
    },
    duration_days: duration,
    duration_label: duration ? `${duration} days` : "",
    travelers: party.total_travelers,
    departure_airports: ["YYZ"],
    budget_cad: request.budget_cad || "",
    max_travel_time_hours: request.max_flight_hours || "",
    flight_preferences: {
      prefer_direct: request.direct_flight_preferred !== false,
    },
    goals: goals.length ? goals : ["great food", "comfort-first planning", "low friction"],
    avoidances: avoidances.length ? avoidances : ["huge crowds", "stressful transfers"],
    pace: request.activity_level || "balanced",
    crowd_tolerance: "low",
    food_priority: "high",
    lodging_preferences: {
      notes: lodgingNotesForParty(party),
    },
    car_rental_expectations: {
      notes: "Decide after checking exact geography, parking, luggage fit, and local driving friction.",
    },
    party,
    freeform_notes: [
      "Prefilled from a Trippy suggestion; edit before saving.",
      rationale ? `Why it fits: ${rationale}` : "",
      risks ? `Watchouts: ${risks}` : "",
      concept.estimated_cost_band_cad
        ? `Cost signal is a template estimate, not live or party-adjusted: ${concept.estimated_cost_band_cad}`
        : "",
    ].filter(Boolean).join("\n"),
  };
}

function parseNightPlanText(text) {
  return String(text || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const parts = line.includes("|")
        ? line.split("|").map((part) => part.trim())
        : line.split(",").map((part) => part.trim());
      let region = parts[0] || "";
      let nights = parts[1] || "";
      if (!nights && line.includes(":")) {
        const colonParts = line.split(":");
        region = colonParts[0].trim();
        nights = colonParts.slice(1).join(":").trim();
      }
      const nightMatch = String(nights || line).match(/\b(\d+)\b/);
      if (!region || !nightMatch) {
        throw new Error(`Stay plan line ${index + 1} needs a region and number of nights.`);
      }
      return {
        region,
        nights: Number(nightMatch[1]),
        lodging_option_id: parts[2] || "",
        notes: parts.slice(3).join(" | "),
      };
    });
}

function partyFromIdeaRequest(request) {
  const partyType = request.party_type || "whole_family";
  const adults = numberOrDefault(request.adults, partyType === "couple" ? 2 : 2);
  const children = ["couple", "adults_only"].includes(partyType)
    ? 0
    : numberOrDefault(request.children, 3);
  const total = numberOrDefault(request.travelers, adults + children);
  const childAges = asList(request.child_ages).map((age) => Number.parseInt(age, 10)).filter((age) => Number.isFinite(age));
  return {
    party_type: partyType,
    adults,
    children,
    child_ages: childAges,
    roster: rosterForParty(partyType, adults, children, childAges),
    total_travelers: total,
    explicit: true,
    defaulted_from_family_profile: false,
    sleeping_considerations: ["couple", "adults_only"].includes(partyType)
      ? ""
      : "At least 3 beds; king strongly preferred for adults",
    separate_rooms_preferred: false,
    privacy_needs: ["couple", "adults_only"].includes(partyType)
      ? ""
      : "Parents need real privacy where practical",
    mobility_notes: "Avoid exhausting transfer days",
    child_friendliness_notes: children ? "Activities should fit the actual children/teens on this trip." : "",
  };
}

function rosterForParty(partyType, adults, children, childAges) {
  if (partyType === "couple") {
    return [
      { name: "Ken", age_band: "adult" },
      { name: "Sue", age_band: "adult" },
    ];
  }
  const roster = [];
  for (let index = 0; index < adults; index += 1) {
    roster.push({ name: index === 0 ? "Ken" : index === 1 ? "Sue" : `Adult ${index + 1}`, age_band: "adult" });
  }
  for (let index = 0; index < children; index += 1) {
    const age = childAges[index];
    roster.push(Number.isFinite(age) ? { name: `Child ${index + 1}`, age } : { name: `Child ${index + 1}`, age_band: "child" });
  }
  return roster;
}

function lodgingNotesForParty(party) {
  if (party.party_type === "couple") {
    return "central, comfortable, high-character stay with a king bed strongly preferred";
  }
  if (party.children > 0) {
    return "comfortable safe base with enough real beds, privacy, and practical access";
  }
  return "comfortable, safe, practical location with good access to food and activities";
}

function asList(value) {
  if (!value) {
    return [];
  }
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean);
  }
  return String(value)
    .replaceAll("\n", ",")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function numberOrDefault(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function planOptionCard(option) {
  const selected = state.trip?.draft?.selected_option_id === option.option_id;
  return `<article class="option-card ${selected ? "selected" : ""}">
    ${optionVisual(option)}
    <div class="option-card-body">
      <div class="option-head">
        <h3>${escapeHtml(option.title)}</h3>
        <span class="metric live">${escapeHtml((option.regions || []).join(" + "))}</span>
      </div>
      <p>${escapeHtml(option.summary)}</p>
      <div class="metric-row">
        <span class="metric">Strength ${option.recommendation_strength}</span>
        <span class="metric">Comfort ${option.family_comfort_score}</span>
        <span class="metric">${escapeHtml(option.island_region_movement_friction)}</span>
      </div>
      <ul class="tight-list">
        ${(option.rationale || []).slice(0, 2).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
        ${(option.major_risks || []).slice(0, 1).map((item) => `<li class="risk">${escapeHtml(item)}</li>`).join("")}
      </ul>
      <button type="button" data-select-option="${escapeHtml(option.option_id)}">${selected ? "Selected" : "Select and research"}</button>
    </div>
  </article>`;
}

function optionVisual(option) {
  const regions = option.regions || [];
  const nightEntries = Object.entries(option.nights_by_region || {});
  const stayCount = nightEntries.filter(([, nights]) => Number(nights) > 0).length || regions.length || 1;
  return `<div class="option-map-thumb option-${Math.min(stayCount, 3)}">
    <div class="map-route-line"></div>
    <div class="map-pin-row">
      ${regions.slice(0, 4).map((region, index) => `<span class="map-pin" style="--pin-index:${index}">${escapeHtml(region)}</span>`).join("")}
    </div>
    <div class="night-plan mini">
      ${nightEntries.map(([region, nights]) => `<article><strong>${escapeHtml(region)}</strong><span>${escapeHtml(nights)} night(s)</span></article>`).join("") || `<article><strong>${escapeHtml(regions.join(" + ") || "Base")}</strong><span>nights TBD</span></article>`}
    </div>
  </div>`;
}

function shortlistCards() {
  const shortlists = state.trip?.shortlists || [];
  if (!shortlists.length) {
    return `<div class="empty-state">No shortlists yet. Select an option to start flights, lodging, cars, and activities automatically.</div>`;
  }
  return shortlists.map(renderShortlistPanel).join("");
}

function renderShortlistPanel(shortlist) {
  if (shortlist.category === "flights") {
    return flightComparison(shortlist);
  }
  if (shortlist.category === "lodging") {
    return lodgingComparison(shortlist);
  }
  return compactShortlist(shortlist);
}

function flightComparison(shortlist) {
  const rows = sortedFlights(shortlist.flight_options || []);
  const recommended = (shortlist.flight_options || []).find((option) => option.option_id === shortlist.recommended_option_id) || rows[0];
  const runner = rows.find((option) => option.option_id !== recommended?.option_id);
  return `<section class="comparison-panel">
    <div class="comparison-head">
      <div>
        <p class="eyebrow">Flights</p>
        <h3>Routing and timing comparison</h3>
        <p>${escapeHtml(shortlist.recommendation_summary || "")}</p>
      </div>
      <div class="compare-tools">
        <span class="metric live">Recommended ${escapeHtml(shortlist.recommended_option_id || "TBD")}</span>
        <label>Sort
          <select id="flightSort">
            ${["best", "cheapest", "shortest", "lowest-friction"].map((value) => `<option value="${value}" ${state.flightSort === value ? "selected" : ""}>${escapeHtml(labelForSort(value))}</option>`).join("")}
          </select>
        </label>
      </div>
    </div>
    ${recommended ? flightRecommendationPanel(recommended, runner) : ""}
    <div class="comparison-table-wrap">
      <table class="comparison-table flight-table">
        <thead>
          <tr>
            <th>Pick</th>
            <th>Airline / source</th>
            <th>Timing</th>
            <th>Route</th>
            <th>Duration</th>
            <th>Price</th>
            <th>Friction</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(flightRow).join("")}
        </tbody>
      </table>
    </div>
  </section>`;
}

function flightRow(option) {
  const isRecommended = option.option_id === recommendedId("flights");
  const layover = (option.layover_airports || []).length
    ? `${option.layover_airports.join(", ")} · ${option.layover_duration || "duration TBD"}`
    : "Nonstop";
  return `<tr class="${isRecommended ? "recommended-row" : ""}">
    <td>
      <span class="flight-label ${isRecommended ? "is-recommended" : ""}">${escapeHtml(option.recommendation_label || option.recommendation_grade || "")}</span>
      <button class="mini-button" type="button" data-select-flight="${escapeHtml(option.option_id)}">${isRecommended ? "Use" : "Choose"}</button>
    </td>
    <td>
      <strong>${escapeHtml(option.airline)}</strong>
      <small>${escapeHtml(option.booking_source)} · ${statusSummary(option)}</small>
    </td>
    <td>
      <strong>${escapeHtml(option.departure_time || "Live verify departure")}</strong>
      <small>${escapeHtml(option.arrival_time || "Live verify arrival")}</small>
    </td>
    <td>
      <strong>${escapeHtml(option.departure_airport)} to ${escapeHtml(option.arrival_airport)}</strong>
      <small>${escapeHtml(option.stops === 0 ? "Nonstop" : `${option.stops} stop(s)`)} · ${escapeHtml(layover)}</small>
    </td>
    <td>
      <strong>${escapeHtml(option.total_travel_duration)}</strong>
      <small>${escapeHtml(option.timing_implication || option.timing_fit || option.traveler_fit || "")}</small>
    </td>
    <td>
      <strong>${escapeHtml(option.price_band)}</strong>
      <small>${escapeHtml(option.fare_estimate_cad || "")}</small>
    </td>
    <td>
      <span class="score-pill">${escapeHtml(option.friction_score)} friction</span>
      <small>${escapeHtml(option.recommendation_rationale || (option.friction_flags || [])[0] || option.recommendation_grade || "")}</small>
      ${evidenceDetails(option)}
    </td>
    <td>${externalLink(option.deep_link, "Open")}</td>
  </tr>`;
}

function flightRecommendationPanel(recommended, runner) {
  return `<div class="recommendation-panel">
    <div>
      <p class="eyebrow">${escapeHtml(recommended.recommendation_label || "Recommended")}</p>
      <h4>${escapeHtml(recommended.airline)}</h4>
      <p>${escapeHtml(recommended.recommendation_rationale || recommended.timing_fit || "")}</p>
      <p class="subtle">${escapeHtml(recommended.date_viability_signal || "")}</p>
    </div>
    ${runner ? `<div>
      <p class="eyebrow">Runner-up</p>
      <strong>${escapeHtml(runner.airline)}</strong>
      <p>${escapeHtml(runner.recommendation_rationale || runner.timing_fit || "")}</p>
    </div>` : ""}
  </div>`;
}

function sortedFlights(rows) {
  const copy = [...rows];
  const recommended = recommendedId("flights");
  if (state.flightSort === "cheapest") {
    return copy.sort((a, b) => numericPrice(a.price_band) - numericPrice(b.price_band));
  }
  if (state.flightSort === "shortest") {
    return copy.sort((a, b) => durationHours(a.total_travel_duration) - durationHours(b.total_travel_duration));
  }
  if (state.flightSort === "lowest-friction") {
    return copy.sort((a, b) => Number(a.friction_score || 99) - Number(b.friction_score || 99));
  }
  return copy.sort((a, b) => {
    if (a.option_id === recommended) return -1;
    if (b.option_id === recommended) return 1;
    return Number(a.rank || 99) - Number(b.rank || 99);
  });
}

function labelForSort(value) {
  return {
    best: "Best overall",
    cheapest: "Cheapest",
    shortest: "Shortest",
    "lowest-friction": "Lowest friction",
  }[value] || value;
}

function truthLegend() {
  return `<div class="truth-legend" aria-label="Data confidence guide">
    <span class="truth-chip verified">Verified from source</span>
    <span class="truth-chip partial">Partial / approximate</span>
    <span class="truth-chip review">Needs manual check</span>
  </div>`;
}

function lodgingStructurePanel(shortlist) {
  const structure = shortlist?.artifacts?.lodging_structure || inferredLodgingStructure();
  if (!structure) {
    return `<div class="empty-state">Choose a trip shape to see one-stay vs split-stay guidance.</div>`;
  }
  const nightPlan = structure.night_plan || [];
  const label = structure.strategy === "split_stay" ? "Split stays" : "One stay";
  const selectedLodging = structure.selected_lodging_option_id
    ? `Selected lodging: ${structure.selected_lodging_option_id}`
    : "No lodging selected yet";
  return `<section class="structure-panel">
    <div>
      <p class="eyebrow">Stay structure</p>
      <h3>${escapeHtml(label)} ${structure.confidence ? `<span>${escapeHtml(structure.confidence)}</span>` : ""}</h3>
      <p>${escapeHtml(structure.summary || "")}</p>
      <p class="subtle">${escapeHtml(selectedLodging)} · ${escapeHtml(structure.data_status || "plan-based")}</p>
    </div>
    <div class="night-plan">
      ${nightPlan.map((item) => `<article>
        <strong>${escapeHtml(item.region)}</strong>
        <span>${escapeHtml(item.nights)} night(s)</span>
      </article>`).join("")}
    </div>
    ${(structure.reasoning || []).length ? `<ul class="tight-list">${structure.reasoning.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
    ${stayStructureForm(structure)}
  </section>`;
}

function stayStructureForm(structure) {
  const strategy = structure.strategy || "single_stay";
  const text = stayStructureText(structure.night_plan || []);
  return `<form id="stayStructureForm" class="stay-structure-form">
    <div>
      <label>Stay approach
        <select name="strategy">
          <option value="single_stay" ${strategy === "single_stay" ? "selected" : ""}>One base</option>
          <option value="split_stay" ${strategy === "split_stay" ? "selected" : ""}>Split stays</option>
        </select>
      </label>
    </div>
    <label>Move nights around
      <textarea name="night_plan_text" rows="4" placeholder="Ponta Delgada | 4 | lodging-1 | central base&#10;Furnas | 3 | lodging-2 | hot springs side">${escapeHtml(text)}</textarea>
    </label>
    <label>Why this structure?
      <textarea name="notes" rows="2" placeholder="What tradeoff are we testing?">${escapeHtml(structure.manual_notes || "")}</textarea>
    </label>
    <div class="button-row">
      <button type="submit">Save stay plan</button>
      <span class="inline-result"></span>
    </div>
    <p class="subtle">Format: region | nights | lodging option ID optional | notes optional. The workspace timeline will use this after you save and refresh the workspace.</p>
  </form>`;
}

function stayStructureText(nightPlan) {
  return nightPlan
    .map((item) =>
      [
        item.region,
        item.nights,
        item.lodging_option_id || "",
        item.notes || "",
      ].filter((value, index) => index < 2 || value).join(" | "),
    )
    .join("\n");
}

function inferredLodgingStructure() {
  const option = selectedPlanOption();
  if (!option) {
    return null;
  }
  const nightEntries = Object.entries(option.nights_by_region || {});
  const stayCount = nightEntries.filter(([, nights]) => Number(nights) > 0).length || option.regions.length;
  const strategy = stayCount > 1 ? "split_stay" : "single_stay";
  return {
    strategy,
    confidence: "plan-based",
    summary:
      strategy === "split_stay"
        ? "The selected shape likely needs multiple stays; verify each move earns its friction cost."
        : "The selected shape is best treated as one base unless exact lodging or flight timing proves otherwise.",
    reasoning: [
      option.lodging_strategy,
      option.island_region_movement_friction,
    ].filter(Boolean),
    night_plan: nightEntries.length
      ? nightEntries.map(([region, nights]) => ({ region, nights }))
      : (option.regions || []).map((region) => ({ region, nights: "TBD" })),
  };
}

function structureGuidancePanel() {
  const flight = recommendedFlight();
  const lodging = shortlistByCategory("lodging");
  const structure = lodging?.artifacts?.lodging_structure || inferredLodgingStructure();
  const bullets = [
    flight?.date_viability_signal,
    flight?.timing_implication,
    structure?.summary,
  ].filter(Boolean);
  if (!bullets.length) {
    return "";
  }
  return `<section class="structure-panel trip-fit-panel">
    <div>
      <p class="eyebrow">Trip-fit guidance</p>
      <h3>Dates, stays, and timing</h3>
      <p>These are planning signals from current evidence, not final inventory truth.</p>
    </div>
    <ul class="tight-list">${bullets.slice(0, 4).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
  </section>`;
}

function numericPrice(value) {
  const match = String(value || "").match(/([\d][\d,]*(?:\.\d{2})?)/);
  return match ? Number(match[1].replace(/,/g, "")) : 999999;
}

function durationHours(value) {
  const match = String(value || "").match(/(\d+(?:\.\d+)?)\s?h(?:ours?)?\s*(?:(\d+)\s?m)?/i);
  if (!match) return 999;
  return Number(match[1]) + Number(match[2] || 0) / 60;
}

function statusSummary(option) {
  const validation = option.validation || {};
  const status = validation.verification_status || option.row_status || "researched";
  const freshness = validation.freshness_status && validation.freshness_status !== "unknown" ? validation.freshness_status : "";
  const confidence = validation.confidence ? `${Math.round(Number(validation.confidence) * 100)}%` : "";
  const adapter = validation.adapter_used ? `${validation.adapter_used}` : "";
  return `<span class="status-badges">
    <span class="status-badge ${status === "live_verified" || option.row_status === "verified_live" ? "ok" : "partial"}">${escapeHtml(status)}</span>
    ${freshness ? `<span class="status-badge">${escapeHtml(freshness)}</span>` : ""}
    ${confidence ? `<span class="status-badge">${escapeHtml(confidence)}</span>` : ""}
    ${adapter ? `<span class="status-badge">${escapeHtml(adapter)}</span>` : ""}
  </span>`;
}

function evidenceDetails(option) {
  const summary = evidenceSummary(option);
  const missing = (option.validation?.missing_fields || []).slice(0, 5).join(", ");
  if (!summary && !missing) {
    return "";
  }
  return `<details class="evidence-details">
    <summary>Evidence</summary>
    ${summary ? `<p>${escapeHtml(summary)}</p>` : ""}
    ${missing ? `<p>Missing: ${escapeHtml(missing)}</p>` : ""}
    ${option.planning_next_step ? `<p>${escapeHtml(option.planning_next_step)}</p>` : ""}
  </details>`;
}

function lodgingComparison(shortlist) {
  const rows = shortlist.lodging_options || [];
  return `<section class="comparison-panel">
    <div class="comparison-head">
      <div>
        <p class="eyebrow">Lodging</p>
        <h3>Fit, location, beds, and value</h3>
        <p>${escapeHtml(shortlist.recommendation_summary || "")}</p>
      </div>
      <span class="metric live">Recommended ${escapeHtml(shortlist.recommended_option_id || "TBD")}</span>
    </div>
    <div class="comparison-table-wrap">
      <table class="comparison-table lodging-table">
        <thead>
          <tr>
            <th>Property / source</th>
            <th>Area</th>
            <th>Beds / party fit</th>
            <th>Cost / flexibility</th>
            <th>Access</th>
            <th>Score</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(lodgingRow).join("")}
        </tbody>
      </table>
    </div>
  </section>`;
}

function lodgingRow(option) {
  const needsThreeBeds = requiresThreeBeds();
  const isRecommended = option.option_id === recommendedId("lodging");
  const bedFit = [
    needsThreeBeds
      ? option.min_three_beds_satisfied === true
        ? "3+ beds"
        : "3+ beds unproven"
      : "party fit to verify",
    option.king_bed_preference_satisfied === true ? "king" : "king unproven",
    option.fit_category || "",
  ].filter(Boolean).join(" · ");
  return `<tr class="${isRecommended ? "recommended-row" : ""}">
    <td>
      <strong>${escapeHtml(option.name)}</strong>
      <small>${escapeHtml(option.source)} · ${escapeHtml(option.lodging_type)} · ${escapeHtml(validationSummary(option))}</small>
    </td>
    <td>
      <strong>${escapeHtml(option.location_area)}</strong>
      <small>${escapeHtml(option.island_or_region || "")}</small>
    </td>
    <td>
      <strong>${escapeHtml(bedFit)}</strong>
      <small>${escapeHtml(option.occupancy_fit || option.adult_child_fit || "")}</small>
    </td>
    <td>
      <strong>${escapeHtml(option.current_price_signal || option.price_band)}</strong>
      <small>${escapeHtml(option.cancellation_notes || "")}</small>
    </td>
    <td>
      <strong>${escapeHtml(option.parking_practicality)}</strong>
      <small>${escapeHtml(option.walkability || option.driving_practicality || "")}</small>
    </td>
    <td>
      <span class="score-pill">${escapeHtml(option.family_comfort_score)} comfort</span>
      <small>${escapeHtml(evidenceSummary(option) || (option.friction_flags || [])[0] || option.comfort_fit || "")}</small>
    </td>
    <td>
      <button class="mini-button" type="button" data-select-lodging="${escapeHtml(option.option_id)}">${isRecommended ? "Use" : "Choose"}</button>
      ${externalLink(option.deep_link, "Open")}
    </td>
  </tr>`;
}

function requiresThreeBeds() {
  const party = state.trip?.intake?.party || state.suggestedIntake?.party || {};
  const total = Number(party.total_travelers || state.trip?.intake?.travelers || 0);
  const children = Number(party.children || 0);
  return total >= 5 || children >= 2;
}

function validationSummary(option) {
  const validation = option.validation || {};
  return [
    validation.verification_status || "manual_required",
    validation.freshness_status && validation.freshness_status !== "unknown" ? validation.freshness_status : "",
    validation.adapter_used,
    validation.confidence ? `${Math.round(Number(validation.confidence) * 100)}%` : "",
  ].filter(Boolean).join(" · ");
}

function evidenceSummary(option) {
  const validation = option.validation || {};
  const artifacts = validation.evidence_artifacts || [];
  const fields = validation.extracted_fields || {};
  const extracted = Object.keys(fields).slice(0, 3).join(", ");
  const artifact = artifacts[0]?.path || artifacts[0]?.url || "";
  return [extracted ? `extracted ${extracted}` : "", artifact ? `evidence ${artifact}` : ""].filter(Boolean).join(" · ");
}

function activitySchedulePanel(shortlist) {
  const schedule = shortlist.artifacts?.activity_schedule;
  const entries = schedule?.entries || [];
  const approved = entries.filter((entry) => ["approved", "booked"].includes(entry.status));
  return `<section class="structure-panel">
    <div>
      <p class="eyebrow">Activity timing</p>
      <h3>Suggested day-by-day fit</h3>
      <p>${escapeHtml(schedule?.summary || "Activities are placed against the current stay plan so you can approve and track them on the timeline.")}</p>
    </div>
    <div class="schedule-strip">
      ${entries.slice(0, 6).map(activityScheduleChip).join("") || `<span class="empty-state">Find activities to see suggested days.</span>`}
    </div>
    <div class="metric-row">
      <span class="metric live">${approved.length} approved</span>
      <span class="metric">${entries.length} suggested</span>
    </div>
  </section>`;
}

function activityScheduleChip(entry) {
  const day = entry.scheduled_day || entry.suggested_day || "TBD";
  const time = entry.scheduled_start_time || entry.suggested_start_time || "";
  const status = entry.status || "researched";
  return `<article class="schedule-chip ${status === "approved" ? "is-approved" : ""}">
    <strong>Day ${escapeHtml(day)}</strong>
    <span>${escapeHtml(time || "time TBD")}</span>
    <small>${escapeHtml(entry.activity_name || "")}</small>
  </article>`;
}

function activityComparison(shortlist) {
  const rows = shortlist.activity_options || [];
  return `<section class="comparison-panel">
    <div class="comparison-head">
      <div>
        <p class="eyebrow">Activities</p>
        <h3>Approve, schedule, and track</h3>
        <p>${escapeHtml(shortlist.recommendation_summary || "")}</p>
      </div>
      <span class="metric live">Recommended ${escapeHtml(shortlist.recommended_option_id || "TBD")}</span>
    </div>
    <div class="comparison-table-wrap">
      <table class="comparison-table activity-table">
        <thead>
          <tr>
            <th>Activity / source</th>
            <th>Suggested slot</th>
            <th>Fit</th>
            <th>Safety / crowd</th>
            <th>Score</th>
            <th>Schedule</th>
            <th></th>
          </tr>
        </thead>
        <tbody>${rows.map(activityRow).join("")}</tbody>
      </table>
    </div>
  </section>`;
}

function activityRow(option) {
  const status = option.row_status || "researched";
  const isApproved = status === "approved" || status === "booked";
  const scheduledDay = option.scheduled_day || option.suggested_day || "";
  const scheduledDate = option.scheduled_date || option.suggested_date || "";
  const start = option.scheduled_start_time || option.suggested_start_time || "";
  const end = option.scheduled_end_time || option.suggested_end_time || "";
  return `<tr class="${isApproved ? "recommended-row" : ""}">
    <td>
      <strong>${escapeHtml(option.activity_name)}</strong>
      <small>${escapeHtml(option.source)} · ${escapeHtml(option.island_location)} · ${escapeHtml(validationSummary(option))}</small>
    </td>
    <td>
      <strong>${scheduledDay ? `Day ${escapeHtml(scheduledDay)}` : "Day TBD"}</strong>
      <small>${escapeHtml([scheduledDate, timeRange(start, end)].filter(Boolean).join(" · "))}</small>
    </td>
    <td>
      <strong>${escapeHtml(option.duration)}</strong>
      <small>${escapeHtml(option.age_family_fit || option.scheduling_rationale || "")}</small>
    </td>
    <td>
      <strong>${escapeHtml(option.group_size_signal)}</strong>
      <small>${escapeHtml(option.review_safety_signal)}</small>
    </td>
    <td>
      <span class="score-pill">${escapeHtml(option.family_pace_fit_score)} pace</span>
      <small>${escapeHtml((option.friction_flags || [])[0] || option.scheduling_rationale || "")}</small>
    </td>
    <td>${activityScheduleForm(option)}</td>
    <td>
      <button class="mini-button" type="button" data-select-activity="${escapeHtml(option.option_id)}">${isApproved ? "Approved" : "Approve"}</button>
      ${externalLink(option.deep_link, "Open")}
    </td>
  </tr>`;
}

function activityScheduleForm(option) {
  return `<form class="inline-schedule-form" data-activity-schedule-form>
    <input type="hidden" name="option_id" value="${escapeHtml(option.option_id)}" />
    <label>Day<input name="day" type="number" min="1" value="${escapeHtml(option.scheduled_day || option.suggested_day || "")}" /></label>
    <label>Date<input name="date" type="date" value="${escapeHtml(option.scheduled_date || option.suggested_date || "")}" /></label>
    <label>Start<input name="start_time" type="time" value="${escapeHtml(option.scheduled_start_time || option.suggested_start_time || "")}" /></label>
    <label>End<input name="end_time" type="time" value="${escapeHtml(option.scheduled_end_time || option.suggested_end_time || "")}" /></label>
    <label class="checkbox-line"><input name="fixed" type="checkbox" ${option.scheduled_flexibility === "fixed" ? "checked" : ""} /> fixed</label>
    <input name="notes" type="text" placeholder="notes" value="${escapeHtml(option.scheduling_notes || "")}" />
    <button class="mini-button secondary" type="submit">Save slot</button>
  </form>`;
}

function timeRange(start, end) {
  if (start && end) return `${start}-${end}`;
  return start || end || "";
}

function carComparison(shortlist) {
  const rows = shortlist.car_options || [];
  return `<section class="comparison-panel">
    <div class="comparison-head">
      <div>
        <p class="eyebrow">Cars</p>
        <h3>Rental price, fit, pickup, and terms</h3>
        <p>${escapeHtml(shortlist.recommendation_summary || "")}</p>
      </div>
      <span class="metric live">Recommended ${escapeHtml(shortlist.recommended_option_id || "TBD")}</span>
    </div>
    <div class="comparison-table-wrap">
      <table class="comparison-table car-table">
        <thead>
          <tr>
            <th>Provider / vehicle</th>
            <th>Pickup / dropoff</th>
            <th>Passenger + luggage fit</th>
            <th>Price + terms</th>
            <th>Friction</th>
            <th>Compare</th>
            <th></th>
          </tr>
        </thead>
        <tbody>${rows.map(carRow).join("")}</tbody>
      </table>
    </div>
  </section>`;
}

function carRow(option) {
  const isRecommended = option.option_id === recommendedId("cars");
  const isApproved = option.row_status === "approved" || option.row_status === "booked";
  const priceSignal = option.validation?.extracted_fields?.price || option.price_band || "live price needed";
  const compareLinks = Object.entries(option.comparison_links || {});
  return `<tr class="${isRecommended || isApproved ? "recommended-row" : ""}">
    <td>
      <strong>${escapeHtml(option.vehicle_class)}</strong>
      <small>${escapeHtml(option.booking_source)} · ${escapeHtml(option.row_status || "researched")} · ${escapeHtml(validationSummary(option))}</small>
    </td>
    <td>
      <strong>${escapeHtml(option.pickup_location)}</strong>
      <small>Dropoff: ${escapeHtml(option.dropoff_location)}</small>
    </td>
    <td>
      <strong>${escapeHtml((option.seating_capacity || "verify") + " seats")}</strong>
      <small>${escapeHtml(option.passenger_fit)} · ${escapeHtml(option.luggage_fit)}</small>
    </td>
    <td>
      <strong>${escapeHtml(priceSignal)}</strong>
      <small>${escapeHtml(option.cancellation_notes)} · ${escapeHtml(option.fees_caution)}</small>
    </td>
    <td>
      <span class="score-pill">${escapeHtml(option.total_friction_score)} friction</span>
      <small>${escapeHtml((option.friction_flags || [])[0] || option.tradeoffs?.[0] || "")}</small>
    </td>
    <td>
      <div class="source-link-list">
        ${externalLink(option.deep_link, option.booking_source || "Open")}
        ${compareLinks.map(([source, link]) => externalLink(link, source)).join("")}
      </div>
    </td>
    <td>
      <button class="mini-button" type="button" data-select-car="${escapeHtml(option.option_id)}">${isApproved ? "Selected" : "Choose"}</button>
    </td>
  </tr>`;
}

function compactShortlist(shortlist) {
  const allOptions = shortlistOptions(shortlist);
  return `<section class="comparison-panel">
    <div class="comparison-head">
      <div>
        <p class="eyebrow">${escapeHtml(shortlist.category)}</p>
        <h3>${escapeHtml(shortlist.category)} shortlist</h3>
        <p>${escapeHtml(shortlist.recommendation_summary || "")}</p>
      </div>
      <span class="metric live">Options ${allOptions.length}</span>
    </div>
    <div class="compact-card-grid">${allOptions.slice(0, 6).map((option) => compactOptionCard(optionForPick(option, shortlist.category))).join("")}</div>
  </section>`;
}

function compactOptionCard(item) {
  return `<article class="compact-option">
    <h4>${escapeHtml(item.title || "Untitled")}</h4>
    <p>${escapeHtml(item.subtitle || "")}</p>
    <div class="metric-row">
      ${item.status ? `<span class="metric ${item.status === "verified_live" ? "live" : ""}">${escapeHtml(item.status)}</span>` : ""}
      ${item.verification ? `<span class="metric">${escapeHtml(item.verification)}</span>` : ""}
    </div>
    ${item.notes ? `<small>${escapeHtml(String(item.notes))}</small>` : ""}
    ${externalLink(item.link, "Open link")}
  </article>`;
}

function embeddedMapPanel(artifact) {
  const pins = artifact.pins || [];
  const primaryMapUrl = artifact.primary_google_maps_url || artifact.exports?.google_maps_route || "";
  const kmlUrl = mapFileUrl("kml");
  const csvUrl = mapFileUrl("csv");
  return `<section class="map-panel">
    <iframe title="Trip planning map" loading="lazy" src="${mapEmbedUrl(primaryMapUrl, pins[0]?.query || artifact.title)}"></iframe>
    <div class="map-side">
      <p class="eyebrow">Custom Google map</p>
      <h3>One ordered trip map</h3>
      <div class="map-actions">
        ${externalLink(primaryMapUrl, "Open Google Map", "primary-link")}
        ${externalLink(kmlUrl, "Google My Maps KML", "secondary-link")}
        ${externalLink(csvUrl, "CSV import", "secondary-link")}
      </div>
      <ol class="map-sequence">
        ${pins.map((pin) => `<li>${externalLink(pin.google_maps_url, pin.label)}<small>${escapeHtml(pin.category)} · ${escapeHtml(pin.notes || "")}</small></li>`).join("")}
      </ol>
    </div>
  </section>`;
}

function fallbackMapPanel(rows) {
  if (!rows.length) {
    return `<div class="empty-state">Build the custom trip map to see all points in order.</div>`;
  }
  const focus = rows[0]?.[0] || "trip map";
  return `<section class="map-panel">
    <iframe title="Trip planning map" loading="lazy" src="${mapsEmbedUrl(focus)}"></iframe>
    <div class="map-side">
      <p class="eyebrow">Workspace map seeds</p>
      <h3>Suggested order</h3>
      <ol class="map-sequence">
        ${rows.slice(0, 12).map((row) => `<li>${externalLink(row[4], row[0])}<small>${escapeHtml(row[1] || "")}</small></li>`).join("")}
      </ol>
    </div>
  </section>`;
}

function mapEmbedUrl(url, fallbackQuery) {
  if (url && url.includes("google.com/maps/dir/")) {
    return `${url}${url.includes("?") ? "&" : "?"}output=embed`;
  }
  return mapsEmbedUrl(fallbackQuery);
}

function mapsEmbedUrl(query) {
  return `https://www.google.com/maps?q=${encodeURIComponent(query || "travel planning")}&output=embed`;
}

function mapFileUrl(kind) {
  if (!state.activeTripId) return "";
  return `/api/map-file?trip_id=${encodeURIComponent(state.activeTripId)}&kind=${encodeURIComponent(kind)}`;
}

function workspaceSummary(workspace) {
  const tabs = workspace.tabs || [];
  const timeline = tabs.find((tab) => tab.name === "Master Timeline");
  const risks = tabs.find((tab) => tab.name === "Risks");
  return `<div class="stage-card">
    <h3>${escapeHtml(workspace.status)}</h3>
    <div class="metric-row">
      ${tabs.map((tab) => `<span class="metric">${escapeHtml(tab.name)} · ${tab.rows.length}</span>`).join("")}
    </div>
    ${workspace.google_sheet_url ? `<p>${externalLink(workspace.google_sheet_url, "Open Google Sheet")}</p>` : ""}
    ${(workspace.next_actions || []).map((item) => `<p>${escapeHtml(item)}</p>`).join("")}
    ${timelinePreview(timeline)}
    ${riskPreview(risks)}
  </div>`;
}

function timelinePreview(tab) {
  const rows = tab?.rows || [];
  if (!rows.length) {
    return "";
  }
  return `<div class="workspace-preview">
    <div class="preview-head">
      <h4>Master Timeline</h4>
      <span>${rows.length} item(s)</span>
    </div>
    <div class="timeline-preview-list">
      ${rows.slice(0, 6).map((row) => `<article>
        <strong>${escapeHtml(row[5] || "Event")} · ${escapeHtml(row[6] || "Untitled")}</strong>
        <small>${escapeHtml([`Day ${row[0]}`, row[1], row[2], row[7]].filter(Boolean).join(" · "))}</small>
        ${row[16] ? `<span class="metric warn">${escapeHtml(row[16])}</span>` : ""}
      </article>`).join("")}
    </div>
  </div>`;
}

function riskPreview(tab) {
  const rows = tab?.rows || [];
  if (!rows.length) {
    return "";
  }
  return `<div class="workspace-preview">
    <div class="preview-head">
      <h4>Top Risks</h4>
      <span>${rows.length} item(s)</span>
    </div>
    <div class="risk-preview-list">
      ${rows.slice(0, 5).map((row) => `<article>
        <strong>${escapeHtml(row[0] || "Risk")}</strong>
        <small>${escapeHtml([row[1], row[2], row[3]].filter(Boolean).join(" · "))}</small>
      </article>`).join("")}
    </div>
  </div>`;
}

function recommendedOptions() {
  const picks = [];
  for (const shortlist of state.trip?.shortlists || []) {
    const options = shortlistOptions(shortlist);
    const recommended = options.find((option) => option.option_id === shortlist.recommended_option_id) || options[0];
    if (recommended) {
      picks.push(optionForPick(recommended, shortlist.category));
    }
  }
  return picks;
}

function shortlistByCategory(category) {
  return (state.trip?.shortlists || []).find((item) => item.category === category);
}

function selectedPlanOption() {
  const draft = state.trip?.draft;
  const selectedId = draft?.selected_option_id || draft?.recommended_option_id;
  return (draft?.options || []).find((option) => option.option_id === selectedId) || null;
}

function recommendedFlight() {
  const shortlist = shortlistByCategory("flights");
  if (!shortlist) {
    return null;
  }
  return (
    (shortlist.flight_options || []).find((option) => option.option_id === shortlist.recommended_option_id) ||
    (shortlist.flight_options || [])[0] ||
    null
  );
}

function recommendedId(category) {
  const shortlist = shortlistByCategory(category);
  return shortlist?.recommended_option_id || "";
}

function optionForPick(option, category) {
  const title = option.airline || option.name || option.vehicle_class || option.activity_name || option.option_id;
  const subtitle = option.location_area || option.island_location || option.departure_airport || option.pickup_location || category;
  const link = option.deep_link;
  const status = option.row_status || "researched";
  const verification = option.validation?.verification_status || "";
  const notes = option.recommendation_grade || option.traveler_fit || option.traveler_roster_supported || "";
  return {
    title,
    subtitle,
    link,
    status,
    verification,
    notes,
    query: `${title} ${subtitle}`,
  };
}

function pickCard(item) {
  return `<article class="pick-card">
    <div class="pick-card-body">
      <h3>${escapeHtml(item.title || "Untitled")}</h3>
      <p>${escapeHtml(item.subtitle || "")}</p>
      <div class="metric-row">
        ${item.status ? `<span class="metric ${item.status === "verified_live" ? "live" : ""}">${escapeHtml(item.status)}</span>` : ""}
        ${item.verification ? `<span class="metric">${escapeHtml(item.verification)}</span>` : ""}
      </div>
      ${item.notes ? `<p>${escapeHtml(String(item.notes))}</p>` : ""}
      ${externalLink(item.link, "Open link")}
    </div>
  </article>`;
}

function shortlistOptions(shortlist) {
  return [
    ...(shortlist.flight_options || []),
    ...(shortlist.lodging_options || []),
    ...(shortlist.car_options || []),
    ...(shortlist.activity_options || []),
  ];
}

function currentDashboardTrip() {
  const planned = state.app?.dashboard?.planned_trips || [];
  return planned.find((trip) => trip.trip_id === state.activeTripId);
}

function collectTrips() {
  const seen = new Set();
  const trips = [];
  for (const trip of state.app?.dashboard?.planned_trips || []) {
    if (!seen.has(trip.trip_id)) {
      trips.push(trip);
      seen.add(trip.trip_id);
    }
  }
  for (const intake of state.app?.intakes || []) {
    if (!seen.has(intake.trip_id)) {
      trips.push(intake);
      seen.add(intake.trip_id);
    }
  }
  return trips;
}

function shortlistReadyCount() {
  const count = state.trip?.shortlists?.length || 0;
  return `${count}/4`;
}

function latestWorkflowId() {
  const workflows = state.trip?.recent_workflows || state.app?.recent_workflows || [];
  return workflows.length ? workflows[workflows.length - 1].id : "";
}

function currentRunLog() {
  return state.trip?.run_log || state.app?.run_log || [];
}

function currentBackendLogPath() {
  return state.trip?.backend_log_path || state.app?.backend_log_path || "";
}

function logRow(event) {
  const details = [
    event.workflow_id ? `workflow ${event.workflow_id}` : "",
    event.proposal_id ? `proposal ${event.proposal_id}` : "",
    event.trip_id || "",
    event.path || "",
  ].filter(Boolean).join(" · ");
  return `<article class="log-row ${escapeHtml(event.severity || "ok")}">
    <div>
      <div class="log-title">${escapeHtml(event.title || event.event_type || "Event")}</div>
      <p>${escapeHtml(event.summary || "")}</p>
      ${details ? `<small>${escapeHtml(details)}</small>` : ""}
    </div>
    <div class="log-meta">
      <span class="metric ${event.status === "verified_live" ? "live" : ""}">${escapeHtml(event.status || "recorded")}</span>
      <time>${escapeHtml(formatTime(event.created_at))}</time>
    </div>
  </article>`;
}

function formatTime(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formPayload(form) {
  const data = new FormData(form);
  const payload = {};
  for (const [key, value] of data.entries()) {
    if (payload[key]) {
      payload[key] = `${payload[key]}, ${value}`;
    } else {
      payload[key] = value;
    }
  }
  form.querySelectorAll("input[type=checkbox]").forEach((input) => {
    payload[input.name] = input.checked;
  });
  return payload;
}

function input(name, label, value, type = "text", attrs = "") {
  return `<label ${attrs}>${label}<input name="${name}" type="${type}" value="${escapeHtml(value ?? "")}"></label>`;
}

function select(name, label, value, options, attrs = "") {
  const normalized = options.map((option) => (typeof option === "string" ? { value: option, label: option.replaceAll("_", " ") } : option));
  return `<label ${attrs}>${label}<select name="${name}">
    ${normalized.map((option) => `<option value="${option.value}" ${option.value === value ? "selected" : ""}>${escapeHtml(option.label)}</option>`).join("")}
  </select></label>`;
}

function textarea(name, label, value, placeholder = "", attrs = "") {
  return `<label class="full" ${attrs}>${label}<textarea name="${name}" rows="2" placeholder="${escapeHtml(placeholder)}">${escapeHtml(value || "")}</textarea></label>`;
}

function rosterText(party) {
  if (party.roster?.length) {
    return party.roster.map((traveler) => `${traveler.name}|${traveler.age ?? traveler.age_band ?? "adult"}`).join(", ");
  }
  if (party.party_type === "couple") {
    return "Ken|adult, Sue|adult";
  }
  return "Ken|adult, Jenn|adult, Child 1|16, Child 2|14, Child 3|11";
}

function partyLabel(value) {
  const found = partyOptions.find((option) => option.value === value);
  return found?.label || String(value || "party TBD").replaceAll("_", " ");
}

function imageBlock(query, label) {
  return `<div class="image-wrap" data-label="${escapeHtml(label)}">
    <img src="${imageUrl(query)}" alt="" loading="lazy" onerror="this.parentElement.classList.add('image-failed')">
  </div>`;
}

function imageUrl(query) {
  const cleaned = String(query || "family travel").replace(/https?:\/\/\S+/g, "").toLowerCase();
  const photos = [
    {
      match: ["sao-miguel-easy", "one-island", "sao miguel"],
      url: "https://images.unsplash.com/photo-1578922746465-3a80a228f223?auto=format&fit=crop&w=900&q=80",
    },
    {
      match: ["two-island", "pico", "faial", "balanced"],
      url: "https://images.unsplash.com/photo-1500534314209-a25ddb2bd429?auto=format&fit=crop&w=900&q=80",
    },
    {
      match: ["ambitious", "terceira", "sampler"],
      url: "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=900&q=80",
    },
    {
      match: ["flight", "airline", "airport", "yyz", "pdl"],
      url: "https://images.unsplash.com/photo-1436491865332-7a61a109cc05?auto=format&fit=crop&w=900&q=80",
    },
    {
      match: ["hotel", "lodging", "rental", "airbnb", "villa", "stay"],
      url: "https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=900&q=80",
    },
    {
      match: ["car", "road", "drive", "pickup", "suv", "van"],
      url: "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=900&q=80",
    },
    {
      match: ["portugal", "lisbon", "porto", "douro"],
      url: "https://images.unsplash.com/photo-1555881400-74d7acaacd8b?auto=format&fit=crop&w=900&q=80",
    },
    {
      match: ["mexico", "oaxaca", "mexico city"],
      url: "https://images.unsplash.com/photo-1518105779142-d975f22f1b0a?auto=format&fit=crop&w=900&q=80",
    },
    {
      match: ["italy", "rome", "florence", "bologna", "venice"],
      url: "https://images.unsplash.com/photo-1523906834658-6e24ef2386f9?auto=format&fit=crop&w=900&q=80",
    },
    {
      match: ["costa rica", "arenal", "manuel antonio", "guanacaste"],
      url: "https://images.unsplash.com/photo-1518182170546-07661fd94144?auto=format&fit=crop&w=900&q=80",
    },
    {
      match: ["food", "restaurant", "oaxaca", "lisbon", "porto"],
      url: "https://images.unsplash.com/photo-1504674900247-0877df9cc836?auto=format&fit=crop&w=900&q=80",
    },
    {
      match: ["whale", "activity", "tour", "hiking", "volcano", "hot springs", "sete cidades", "furnas"],
      url: "https://images.unsplash.com/photo-1551632811-561732d1e306?auto=format&fit=crop&w=900&q=80",
    },
    {
      match: ["map", "route", "transit"],
      url: "https://images.unsplash.com/photo-1524661135-423995f22d0b?auto=format&fit=crop&w=900&q=80",
    },
    {
      match: ["azores", "island", "ocean", "beach", "coast"],
      url: "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=900&q=80",
    },
    {
      match: ["japan", "tokyo", "kyoto"],
      url: "https://images.unsplash.com/photo-1540959733332-eab4deabeeaf?auto=format&fit=crop&w=900&q=80",
    },
  ];
  const selected = photos.find((photo) => photo.match.some((term) => cleaned.includes(term)));
  return selected
    ? selected.url
    : "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=900&q=80";
}

function setWorking(element, text) {
  if (element) {
    element.textContent = `${text}...`;
  }
}

function externalLink(url, label, className = "") {
  if (!url) {
    return "";
  }
  const classAttr = className ? ` class="${escapeHtml(className)}"` : "";
  return `<a${classAttr} href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label || "Open")}</a>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
