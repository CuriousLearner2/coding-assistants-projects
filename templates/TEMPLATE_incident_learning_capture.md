---
name: template-incident-learning-project-name-date
description: "Template for capturing incident, fixes, and lessons learned"
metadata: 
  node_type: memory
  type: project
  date: 
    - YYYY-MM-DD
  severity: 
    - low/medium/high/critical
  resolution: 
    - in-progress/complete
  applies_to: 
    - Playwright
    - API testing
    - CI/CD
    - etc.
  originSessionId: c0af23d1-213e-4363-bbff-e6e5007bda11
---

# [PROJECT_NAME] Incident - [YYYY-MM-DD]

## Quick Reference

| Aspect | Details |
|--------|---------|
| **Problem** | One sentence describing what happened |
| **Root Cause** | The underlying issue (not the symptom) |
| **Impact** | What broke, how badly, for how long |
| **Resolution Time** | How long to fix |
| **Prevention** | What we installed to prevent recurrence |
| **Transferability** | Other projects this applies to |

---

## Incident Summary

**Timeline:** [Start time] - [End time]  
**Duration:** [X minutes/hours]  
**Impact:** [e.g., 43 tests hung; suite never completed]  
**Root Cause:** [Primary underlying issue]  
**Resolution:** [Type of fix: code change/automation/documentation]  
**Prevention:** [Mechanism installed]  

---

## What Happened

### Initial State
- [Describe the healthy state before the incident]
- [What was expected to work]

### Failure Pattern
```
[Show the failure sequence or symptom timeline]
Example:
Test 1: FAILED [timeout]
Test 2: FAILED [timeout]
Test 3: BLOCKED (waiting on Test 1-2)
...
Total impact: [X hours] of wasted time
```

### Why Tests Didn't Fail Fast
- [What prevented early detection?]
- [Why did it cascade?]

---

## Root Causes (Layered Analysis)

### Layer 1: [Immediate Cause]
- **Problem:** [Specific issue]
- **Why it fails:** [Mechanism of failure]
- **Result:** [What breaks]
- **Severity:** [Blocks: Y/N, Cascades: Y/N]

### Layer 2: [Secondary/Amplification]
- **Problem:** 
- **Why it fails:** 
- **Result:** 
- **Severity:** 

### Layer 3: [Structural/Systemic]
- **Problem:** 
- **Why it fails:** 
- **Result:** 
- **Severity:** 

### Layer 4: [Detection/Prevention Gap]
- **Problem:** [Why wasn't this caught earlier?]
- **Why it fails:** [What allowed it to recur?]
- **Result:** [Pattern can be introduced again]
- **Severity:** [Preventable: Y/N]

---

## Fixes Applied

### Fix 1: [Short description]
**Code change:**
```python
# Before
[problematic code]

# After
[fixed code]
```

**Impact:** [What this achieves]

**Verification:**
```bash
# How to verify this fix works
[Test command]
```

### Fix 2: [Short description]
...

---

## Prevention Mechanisms Installed

### Mechanism 1: [Automation/Hook/Policy]
- **Location:** [Where it lives]
- **Function:** [What it does]
- **Trigger:** [When it runs]
- **Maintenance:** [Ongoing effort required]

### Mechanism 2: [Documentation/Guideline]
- **Location:** [Where it lives]
- **Function:** [What it accomplishes]
- **Audience:** [Who needs to follow it]
- **Enforcement:** [How is it enforced?]

---

## Lessons Learned

### For This Project
1. **Lesson 1:** [Insight about this specific project's architecture]
   - **Why it matters:** [Impact on future work]

2. **Lesson 2:**
   - **Why it matters:** 

### For Other Projects
1. **Pattern 1:** [Generalizable insight]
   - **Applies to:** [Other contexts: testing, CI/CD, API, etc.]
   - **Why it matters:** [Why this prevents similar issues]

2. **Pattern 2:**
   - **Applies to:** 
   - **Why it matters:** 

### Technology-Agnostic Insights
- [Insights that apply across any tech stack]
- [Patterns that recur in different contexts]

---

## Metrics & Monitoring

**Before fixes:**
- [Quantify the problem]
- [Example: Suite execution time, test timeout frequency, number of cascading failures]

**After fixes:**
- [Quantify the improvement]
- [Example: 110x faster, zero timeouts, no cascades]

**Monitoring strategy:**
```bash
# Commands to detect recurrence
[Monitoring commands]
```

---

## Transferability to Other Projects

### Directly Applicable To
- [Specific contexts where this applies without modification]

### Pattern to Replicate
1. [Generalizable technique 1]
2. [Generalizable technique 2]
3. [Generalizable technique 3]

### Documents/Artifacts to Copy
- [Skills, templates, or tools that transfer]
- [Documentation that applies broadly]

---

## Future Work

### Immediate (Before Next Feature)
- [ ] [Action 1]
- [ ] [Action 2]
- [ ] Verify prevention mechanisms are in place

### Medium Term (This Quarter)
- [ ] [Action 3]
- [ ] [Action 4]
- [ ] Share learnings with [Team/Organization]

### Long Term (Next Project)
- [ ] Apply prevention pattern to [New project]
- [ ] Enhance [Documentation] with additional insights
- [ ] [Organizational change]

---

## Reference Information

**Files Modified:** [List of files changed]  
**Commits:** [Git commit SHAs and messages]  
**Time Spent:** [Total time investigating + fixing]  
**ROI:** [Prevention time saved if pattern prevents recurrence]  

---

## Contact & Escalation

**If this issue recurs:**
1. Check: [Command to verify]
2. Reference: [Documentation to read]
3. Escalate to: [Who should know]

**For similar issues in other projects:**
- Review: [SKILL_RESILIENT_TEST_DESIGN.md equivalent]
- Apply: [Prevention mechanism template]
- Document: [Update this memory with new variations]

---

**Incident Status:** [RESOLVED / IN PROGRESS]  
**Prevention Status:** [AUTOMATED / MANUAL / NONE]  
**Documentation Status:** [COMPLETE / IN PROGRESS]  
**Knowledge Transfer Status:** [DONE / IN PROGRESS / PENDING]  

---

## Appendix: Key Code Examples

### Pattern to Avoid
```python
# ❌ Anti-pattern (what caused the incident)
[problematic code example]
```

### Pattern to Follow
```python
# ✅ Correct pattern (after fixing)
[correct code example]
```

### Verification Checklist
- [ ] [Check 1]
- [ ] [Check 2]
- [ ] [Check 3]
