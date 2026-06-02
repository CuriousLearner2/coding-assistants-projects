# TEMPLATE: CLAUDE.md for [PROJECT_NAME]

**This file goes in the project root directory and provides:**
- Critical requirements and "never do this" patterns
- Common problems and their solutions
- Quick reference for contributors
- Links to detailed documentation

**Location:** `[PROJECT_ROOT]/CLAUDE.md`

**Copy this template and customize for your project**

---

# Claude Code Guidelines for [PROJECT_NAME]

## Quick Navigation

- [Critical Requirements](#critical-requirements) - Non-negotiables
- [Workflow](#workflow) - How to work on this project
- [Problem Solving](#problem-solving) - Troubleshooting guide
- [Key Documents](#key-documents) - Where to find details

---

## Critical Requirements

### Requirement 1: [Specific rule]

**NEVER do this:**
```python
# ❌ BLOCKED by [validation mechanism]
[problematic code pattern]
```

**ALWAYS do this:**
```python
# ✅ REQUIRED
[correct code pattern]
```

**Why it matters:**
- [Consequence 1]
- [Consequence 2]
- [Reference: incident memory if applicable]

### Requirement 2: [Specific rule]

**NEVER:**
```
[what not to do]
```

**ALWAYS:**
```
[what to do]
```

**Why it matters:**
- [Impact]

---

## Before You Start

### New to this project?

1. Read [SKILL_*.md](#key-documents) (XX min)
2. Run the [Verification Checklist](#verification)
3. Review [Recent Incidents](#incident-history) to understand why rules exist
4. Ask: "Who did this last time?" and learn from them

### About to make changes?

1. Check [Requirements](#critical-requirements) above
2. Follow [Workflow](#workflow) steps
3. Run [Verification](#verification) before committing
4. Reference [Key Documents](#key-documents) if stuck

---

## Workflow

### Setup

```bash
# Clone and enter project
cd [PROJECT_NAME]

# Activate environment
[source .venv/bin/activate / poetry shell / etc.]

# Install dependencies
[pip install / poetry install / npm install / etc.]

# Verify setup
[test command to verify working environment]
```

### Development

```bash
# Create branch
git checkout -b [feature/bugfix/incident-name]

# Make changes following [Requirements](#critical-requirements)

# Test your changes
[test command 1]
[test command 2]

# Verify against checklist
[verification commands]

# Commit (pre-commit hook will validate)
git commit -m "..."
```

### Testing

**Unit / Integration Tests:**
```bash
[test command]
```

**E2E / Visual / Load Tests:**
```bash
[test command]
```

**Full Verification:**
```bash
# This runs all checks
[comprehensive test command]
```

---

## Common Issues & Solutions

### Issue 1: [Common problem name]

**Symptoms:**
- [What you observe]
- [What error messages appear]

**Root cause:**
- [Why it happens]

**Solution:**
```bash
# Fix the issue
[diagnostic command]
[fix command]
[verification command]
```

**Prevention:**
- [How to avoid in future]
- Reference: [Key document for details]

### Issue 2: [Common problem name]

**Symptoms:**

**Root cause:**

**Solution:**

**Prevention:**

### If all else fails:

1. Check [incident memory](#incident-history)
2. Search [Key Documents](#key-documents)
3. Run diagnostic: `[diagnostic command]`
4. Escalate to: [Who should know]

---

## Verification

**Before committing, run:**

```bash
# 1. Check for patterns we block
[grep/lint command for anti-patterns]

# 2. Test your changes
[test command]

# 3. Run full suite
[full test command]

# 4. Check performance
[performance check command]
```

**Red flags (stop and fix):**
- [Anti-pattern 1 detected]
- [Test takes > X seconds]
- [Performance metric below Y]

---

## Key Documents

### Must Read (In Order)

| Document | Time | Purpose | When to Use |
|----------|------|---------|------------|
| [SKILL_*.md](#) | 30min | How to build/test this correctly | Writing new code |
| [INCIDENT_HISTORY.md](#) | 10min | Why these rules exist | Understanding requirements |
| [ARCHITECTURE.md](#) | 20min | How components fit together | Making design decisions |

### Reference (As Needed)

| Document | Purpose |
|----------|---------|
| [CLAUDE.md](#) | This file - quick ref |
| [TESTING_GUIDE.md](#) | Detailed testing patterns |
| [DEPLOYMENT.md](#) | How to ship code |
| [PERFORMANCE.md](#) | Optimization guidelines |

### Incident History

**Recent incidents and what we learned:**

- **[DATE] Incident Name** → [SKILL_*.md] / [Memory link]
  - Problem: [One sentence]
  - Prevention: [What we installed]
  - Status: [RESOLVED / MONITORING]

---

## Architecture & Dependencies

### Key Components

```
[PROJECT_STRUCTURE]
├── [Component 1]: [Brief description]
├── [Component 2]: [Brief description]
└── [Component 3]: [Brief description]
```

### Critical Dependencies

- [Dependency 1] (version [X.Y.Z]) - [Why critical]
- [Dependency 2] - [Why critical]

### Known Limitations

- [Limitation 1] - [Workaround]
- [Limitation 2] - [Workaround]

---

## Environment & Configuration

### Required

```bash
# Check these are installed
[python --version / node --version / etc.]
[dependency --version]

# Required env vars
[export VAR1=value]
[export VAR2=value]
```

### Optional

- [Optional tool 1]: [What it enables]
- [Optional tool 2]: [What it enables]

### Common Configuration Issues

**Problem:** [Setup issue]
**Solution:** [Fix with commands]

---

## Performance Targets

**Metrics we track:**

| Metric | Target | Red Flag | Where to Fix |
|--------|--------|----------|-------------|
| [Metric 1] | [Target] | > [Bad value] | [File/area] |
| [Metric 2] | [Target] | > [Bad value] | [File/area] |

**Monitoring:**
```bash
# Track performance
[monitoring command]
```

---

## Incident Response

### If something breaks:

1. **Assess impact:** How many [users/tests/systems] affected?
2. **Immediate action:** [Rollback / Hotfix / Monitor]
3. **Investigation:** Check [log file / error tracking / incidents]
4. **Resolution:** [Steps to fix]
5. **Post-mortem:** [Review incident memory]

### For test failures:

**Intermittent failures?**
- Check [TESTING_GUIDE.md]
- Search [incident memory] for similar issues
- May indicate [race condition / timeout / environment issue]

**Consistent failures?**
- `[diagnostic command]`
- `[test with verbose output]`
- Reference: [Common Issues](#common-issues--solutions)

---

## For Code Reviewers

**When reviewing changes to this project:**

1. ✅ Verify [Critical Requirements](#critical-requirements) are followed
2. ✅ Check for [Common Issues](#common-issues--solutions)
3. ✅ Ask "Have we seen this pattern cause problems?" (check [incident memory](#incident-history))
4. ✅ Ensure [Verification](#verification) checklist was run
5. ✅ Reference [Key Documents](#key-documents) if changes need explanation

---

## For Contributors

**First time contributing?**

1. Read [SKILL_*.md](#key-documents) (30 min)
2. Review [Critical Requirements](#critical-requirements)
3. Work through [Workflow](#workflow)
4. Ask questions about [incident history](#incident-history)

**Adding a new feature?**

1. Check if [related incident](#incident-history) exists
2. Follow [Critical Requirements](#critical-requirements)
3. Write tests (reference [TESTING_GUIDE.md](#key-documents))
4. Run [Verification](#verification) before submitting

**Debugging a failure?**

1. Check [Common Issues](#common-issues--solutions)
2. Search [incident memory](#incident-history) for similar pattern
3. Reference [TROUBLESHOOTING.md](#key-documents)
4. Escalate if blocked

---

## Escalation & Support

**Stuck? Try this order:**

1. Search this file (Ctrl+F)
2. Read [Key Documents](#key-documents)
3. Check [incident memory](#incident-history)
4. Run diagnostic: `[diagnostic command]`
5. Ask [Domain expert / Team / Original author]

**Reporting issues:**

- Include: [What you did] + [What happened] + [What you expected]
- Run: `[diagnostic command]` and share output
- Reference: Which [Critical Requirement](#critical-requirements) did it involve?

---

## Maintenance

### Regular Tasks

- [ ] Review [metric targets](#performance-targets) (monthly)
- [ ] Update [incident history](#incident-history) if patterns emerge
- [ ] Run [full verification](#verification) before releases
- [ ] Check [dependencies](#critical-dependencies) for security updates

### When this document gets out of date

- [Critical Requirement](#critical-requirements) is no longer relevant? Remove it
- [Common Issue](#common-issues--solutions) is outdated? Update or remove
- New incident happened? Add to [incident history](#incident-history) and update [Key Documents](#key-documents)

---

## Quick Reference Card

**Copy/paste this as a comment in your editor:**

```
╔════════════════════════════════════════════════╗
║          [PROJECT] Critical Rules              ║
╠════════════════════════════════════════════════╣
║ ✋ NEVER: [anti-pattern 1]                      ║
║ ✋ NEVER: [anti-pattern 2]                      ║
║ ✅ ALWAYS: [pattern 1]                         ║
║ ✅ ALWAYS: [pattern 2]                         ║
║                                                ║
║ Before Committing:                             ║
║ $ [verification command]                       ║
║ $ [test command]                               ║
║                                                ║
║ Stuck? → Read CLAUDE.md → Key Documents       ║
╚════════════════════════════════════════════════╝
```

---

**Last Updated:** [YYYY-MM-DD]  
**Status:** [Active / Experimental / Deprecated]  
**Next Review:** [YYYY-MM-DD]  
**Maintained By:** [Name / Team]
