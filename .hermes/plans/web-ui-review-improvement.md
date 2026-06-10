# Plan: Review and Improve OB/GYN Wiki Web UI

**Goal:** Review the current `web/index.html` SPA and identify concrete improvements in UX, performance, accessibility, and maintainability. Then implement high-value changes.

## Current State Analysis (to be done first)

- Single-file `index.html` (~745 lines)
- Uses vis-network for graph visualization
- Right-side info panel + top-left search panel
- Supports both live API mode and static export mode
- Dark theme with GitHub-inspired colors

## Proposed Improvements

### Phase 1: Review & Audit (High Priority)
1. **Code quality audit**
   - Identify duplicated logic between live and static modes
   - Check for missing error handling on API calls
   - Review JavaScript organization (currently one large script block)

2. **UX improvements**
   - Add loading states / skeleton for graph initialization
   - Improve node search (fuzzy + keyboard navigation)
   - Add "Expand node" functionality from info panel (already partially present)
   - Better mobile / touch support
   - Add legend for node types and edge evidence levels

3. **Performance**
   - Consider lazy loading of vis-network if possible
   - Reduce initial payload size of `graph_data.json` for static mode
   - Add clustering / physics tuning for large graphs (178+ nodes)

4. **Accessibility & Polish**
   - ARIA labels on controls
   - Keyboard shortcuts (e.g., `/` to focus search)
   - Consistent hover / active states
   - Export graph as PNG / SVG button

### Phase 2: Implementation Priorities (Recommended order)
1. Extract JavaScript into `web/assets/app.js` (better maintainability)
2. Add node type legend + evidence level legend
3. Improve search with keyboard arrow navigation + Enter to select
4. Add "Focus on node" + "Expand connections" buttons in info panel
5. Add loading indicator on initial graph render
6. Add keyboard shortcut `/` to focus search

### Phase 3: Validation
- Test in both live API mode (`localhost:8765`) and static mode (`web/dist`)
- Run visual regression on key interactions
- Verify no regression on existing graph expansion / SSE features

## Files Involved
- `web/index.html` (main target)
- `web/assets/app.js` (proposed new file)
- `scripts/build_static.py` (may need update for new assets)
- `obgyn_wiki/api_server.py` (if new API endpoints needed)

## Success Criteria
- Cleaner, more maintainable codebase
- Noticeably better UX for exploring the 178-node graph
- No breakage in static export or live mode

**Owner:** Superpowers workflow (planning → delegation → review)