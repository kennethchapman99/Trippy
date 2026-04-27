# Backend route inventory

/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:774:            if path == "/api/state":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:777:            if path == "/api/logs":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:783:            if path == "/api/trip":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:791:            if path == "/api/map-file":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:813:            if path == "/api/intake":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:816:            if path == "/api/suggest-ideas":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:819:            if path == "/api/draft":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:822:            if path == "/api/select":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:827:            if path == "/api/shortlist":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:838:            if path == "/api/lodging-candidate":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:841:            if path == "/api/flight-candidate":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:844:            if path == "/api/select-flight":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:847:            if path == "/api/select-lodging":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:850:            if path == "/api/lodging-structure":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:853:            if path == "/api/lodging-structure-suggestions":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:856:            if path == "/api/planning-advice":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:859:            if path == "/api/select-activity":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:862:            if path == "/api/schedule-activity":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:865:            if path == "/api/select-car":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:868:            if path == "/api/trip-packet/item":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:871:            if path == "/api/workspace":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:880:            if path == "/api/map":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:883:            if path == "/api/feedback":
/Users/kchapman/Hermes/Trippy/trippy/ui/server.py:886:            if path == "/api/delete-trip":
Binary file /Users/kchapman/Hermes/Trippy/trippy/ui/__pycache__/server.cpython-311.pyc matches
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:107:  state.app = await apiGet("/api/state");
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:122:    state.app = await apiGet("/api/state");
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:128:  state.trip = await apiGet(`/api/trip?trip_id=${encodeURIComponent(tripId)}`);
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:223:    ? `/api/logs?trip_id=${encodeURIComponent(state.activeTripId)}`
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:224:    : "/api/logs";
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:439:  await apiPost("/api/delete-trip", { trip_id: tripId });
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1066:    const response = await apiPost("/api/intake", payload);
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1073:      const draft = await apiPost("/api/draft", { trip_id: response.intake.trip_id });
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1120:    const response = await apiPost("/api/draft", { trip_id: state.activeTripId });
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1134:    const selection = await apiPost("/api/select", {
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1141:      const response = await apiPost("/api/shortlist", {
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1166:      await runStage(root, "research", "/api/shortlist", {
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1187:        const response = await apiPost("/api/lodging-candidate", payload);
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1209:        const response = await apiPost("/api/flight-candidate", payload);
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1224:        const response = await apiPost("/api/select-flight", {
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1261:        const response = await apiPost("/api/flight-candidate", payload);
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1276:        const response = await apiPost("/api/select-flight", {
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1304:        const response = await apiPost("/api/lodging-structure", {
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1325:        const response = await apiPost("/api/lodging-structure", {
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1366:        const response = await apiPost("/api/lodging-candidate", payload);
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1381:        const response = await apiPost("/api/select-lodging", {
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1408:    const lodging = await apiPost("/api/shortlist", {
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1417:    const structure = await apiPost("/api/lodging-structure-suggestions", {
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1437:        const response = await apiPost("/api/select-car", {
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1455:        const response = await apiPost("/api/select-activity", {
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1475:        const response = await apiPost("/api/schedule-activity", {
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1503:      await runStage(root, "plan", "/api/workspace", {
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1515:      await runStage(root, "plan", "/api/map", { trip_id: state.activeTripId });
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1527:    await runStage(root, "plan", "/api/workspace", {
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1544:      await runStage(root, stage, "/api/shortlist", {
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1576:        const response = await apiPost("/api/trip-packet/item", payload);
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1592:      await runStage(root, "workspace", "/api/workspace", {
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1606:      await runStage(root, "maps", "/api/map", { trip_id: state.activeTripId });
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1635:        const response = await apiPost("/api/feedback", payload);
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1758:        const response = await apiPost("/api/suggest-ideas", payload);
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1763:        state.app = await apiGet("/api/state");
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1794:        const response = await apiPost("/api/feedback", payload);
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:1800:        state.app = await apiGet("/api/state");
/Users/kchapman/Hermes/Trippy/trippy/ui/static/app.js:3132:  return `/api/map-file?trip_id=${encodeURIComponent(state.activeTripId)}&kind=${encodeURIComponent(kind)}`;
/Users/kchapman/Hermes/Trippy/trippy/ui/templates/index.html:23:          <a id="dashboardJsonLink" href="/api/state" title="Open backend state">Data</a>
/Users/kchapman/Hermes/Trippy/trippy/ui/templates/index.html:24:          <a id="logsJsonLink" href="/api/logs" title="Open workflow logs">Logs</a>
Binary file /Users/kchapman/Hermes/Trippy/trippy/services/__pycache__/trip_ideation.cpython-311.pyc matches
Binary file /Users/kchapman/Hermes/Trippy/trippy/services/__pycache__/trip_planner.cpython-311.pyc matches
Binary file /Users/kchapman/Hermes/Trippy/trippy/services/__pycache__/lodging_shortlist.cpython-311.pyc matches
Binary file /Users/kchapman/Hermes/Trippy/trippy/services/__pycache__/trip_map_builder.cpython-311.pyc matches
Binary file /Users/kchapman/Hermes/Trippy/trippy/services/__pycache__/map_outputs.cpython-311.pyc matches
