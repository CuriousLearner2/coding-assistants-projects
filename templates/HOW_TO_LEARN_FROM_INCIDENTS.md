---
name: how-to-learn-from-incidents
description: Process for capturing and transferring incident learnings across projects
metadata: 
  node_type: memory
  type: reference
  applies_to: any-incident-or-complex-problem
  originSessionId: c0af23d1-213e-4363-bbff-e6e5007bda11
---

# How to Learn from Incidents & Complex Problems

**Use this guide when:**
- You've solved a complex problem and want to prevent recurrence
- You want to transfer learnings to other projects
- You're starting a new project and want to apply previous lessons
- You need to onboard someone to a new domain

---

## Overview: The 4-Step Learning Capture System

```
Step 1: Document the Incident (Permanent Memory)
   ↓
Step 2: Create Reusable Skill (Transferable Knowledge)
   ↓
Step 3: Create Project Guidelines (Local Rules)
   ↓
Step 4: Automate Prevention (Zero-Effort Enforcement)
```

**Result:** Knowledge captured once, applied everywhere automatically.

---

## Step 1: Document the Incident (Persist Memory)

**Template:** `TEMPLATE_incident_learning_capture.md`

**What to do:**
- Use this template to document what happened
- Explain root causes (don't just describe symptoms)
- Record what you fixed
- Capture lessons learned

**Output:** `.claude/projects/[project]/memory/[incident-name].md`

**Example:**
```markdown
# Givebutter E2E Test Incident - 2026-06-01
[Complete incident analysis using template]
```

**How to reference this memory:**
```
In future conversations, ask:
"Check my memory on E2E test cascading failures"
"What did we learn about test interdependencies?"
```

**Why it matters:**
- ♾️ Permanent record of what went wrong and why
- 🔍 Searchable when similar issues appear in other projects
- 👥 Helps team understand context
- 📊 Enables trend spotting (if same issue recurs)

---

## Step 2: Create Reusable Skill (Transferable Knowledge)

**Template:** `TEMPLATE_reusable_skill.md`

**What to do:**
- Extract generalizable patterns from the incident
- Document the "right way" to do something
- Include code examples, not just theory
- Make it technology-agnostic where possible

**Output:** Save as `SKILL_[DOMAIN]_[TOPIC].md` in project or shared location

**Example:**
```markdown
# SKILL: Resilient Test Plan & Test Case Design

[Complete guide using template]
```

**How to reference this skill:**
```
In new projects:
"Copy SKILL_RESILIENT_TEST_DESIGN.md to this project"
"Review [SKILL_NAME] before writing tests"
```

**Why it matters:**
- 📚 Becomes a resource for future projects
- 🎓 Teaches the "why" behind patterns
- 🔄 Can be customized per project
- 👨‍🏫 Helps with onboarding and training

---

## Step 3: Create Project Guidelines (Local Rules)

**Template:** `TEMPLATE_project_claude_md.md`

**What to do:**
- Create `CLAUDE.md` in your project root
- Document project-specific "never do this" rules
- Provide quick troubleshooting guide
- Link to detailed documentation

**Output:** `[PROJECT_ROOT]/CLAUDE.md`

**Example:**
```markdown
# Claude Code Guidelines for Givebutter

## Critical Requirements
- NEVER: wait_for_selector('input[type="file"]')
- ALWAYS: wait_for_selector('div.drop-zone', timeout=5000)

[Full guidelines using template]
```

**How to reference this:**
```
Contributors read:
"See CLAUDE.md for critical requirements"

You check:
"What does CLAUDE.md say about this?"
```

**Why it matters:**
- ⚡ Fast reference for everyone working on project
- 🚫 Catches common mistakes immediately
- 📋 Centralizes problem-solving guide
- 🎯 Enforces consistency

---

## Step 4: Automate Prevention (Zero-Effort Enforcement)

**Template:** `TEMPLATE_automation_prevention.md`

**What to do:**
- Create pre-commit hooks to block anti-patterns
- Add linter rules for code quality
- Set up CI/CD checks
- Create monitoring to detect issues early

**Output:**
- `.git/hooks/pre-commit` (runs automatically on every commit)
- `.github/workflows/[check].yml` (runs on every push)
- `scripts/monitor-health.sh` (runs on schedule)

**Example:**
```bash
#!/bin/bash
# .git/hooks/pre-commit
if git diff --cached | grep -q "wait_for_selector('input\[type=\"file\"\]')"; then
    echo "❌ Error: Hidden file input selectors detected"
    exit 1
fi
```

**How to reference this:**
```
Developers don't think about it—automation just blocks them.

If blocked:
"Read CLAUDE.md → Key Documents → SKILL_[NAME].md"
```

**Why it matters:**
- 🤖 Humans don't have to remember rules
- 🛡️ Prevents anti-patterns automatically
- 📊 Detects issues before they cause problems
- ♾️ Works forever with zero maintenance

---

## Quick Start: Using These Templates

### For Your First Incident

```bash
# 1. Choose a recent incident you've solved
# 2. Copy the incident template
cp TEMPLATE_incident_learning_capture.md \
   ~/.claude/projects/-Users-gautambiswas-Claude-Code/memory/[incident-name].md

# 3. Fill it out with your details
# 4. Update the memory index (MEMORY.md)
```

### For Your Next Project

```bash
# 1. Copy templates to new project
cp TEMPLATE_project_claude_md.md [NEW_PROJECT]/CLAUDE.md
cp TEMPLATE_reusable_skill.md [NEW_PROJECT]/SKILL_[DOMAIN].md
cp TEMPLATE_automation_prevention.md [NEW_PROJECT]/PREVENTION.md

# 2. Customize each template with project specifics
# 3. Install pre-commit hooks immediately
# 4. Share CLAUDE.md with team on day 1
```

### For Existing Projects

```bash
# 1. Copy incident template for each recent incident
# 2. Create/update CLAUDE.md with critical rules
# 3. Install pre-commit hooks (can do retroactively)
# 4. Document lessons learned in skill files
```

---

## Template Map: Which Template for What?

```
Situation                          → Use Template
─────────────────────────────────────────────────────
Just solved a complex problem      → TEMPLATE_incident_learning_capture.md
Want to teach a pattern            → TEMPLATE_reusable_skill.md
Starting a new project             → TEMPLATE_project_claude_md.md
Need to prevent pattern recurrence → TEMPLATE_automation_prevention.md
Unsure which to use                → Start with incident, then derive others
```

---

## Example: Full Learning Capture Flow

### Day 1: Incident Happens
```
E2E tests hang for 30 minutes
↓ Investigate
Hidden selector issue
↓ Fix it
Replace 38 instances of hidden selector
↓ Document
Create givebutter_e2e_test_incident.md
```

### Day 2: Create Reusable Knowledge
```
Extract general patterns
↓ Create skill
SKILL_RESILIENT_TEST_DESIGN.md (399 lines)
↓ Make it technology-agnostic
Can apply to Selenium, Cypress, Puppeteer, etc.
```

### Day 3: Implement Project Rules
```
Define "never do this" rules
↓ Create CLAUDE.md
Critical requirements + troubleshooting guide
↓ Share with team
Every contributor reads on day 1
```

### Day 4: Automate Prevention
```
Create pre-commit hook
↓ Test it blocks the anti-pattern
Hook prevents future instances
↓ Set it up in CI/CD
GitHub Actions validates all PRs
↓ Install monitoring
Daily health checks detect issues early
```

### Day 5+: Reuse Everywhere
```
New project? Copy templates
↓ Customize for domain
↓ Install hooks
↓ Share CLAUDE.md
Next time: 8 hours → 2 hours to prevent similar issues
```

---

## How Humans Reference Your Learning

### Developer on Givebutter Project
```
"I'm stuck on E2E tests"
↓ Check CLAUDE.md (3 min)
↓ Read SKILL_RESILIENT_TEST_DESIGN.md (15 min)
↓ Problem solved, or escalate with clear reference
```

### Developer on New Project (Similar Domain)
```
"We need E2E tests"
↓ Copy SKILL_RESILIENT_TEST_DESIGN.md (5 min)
↓ Customize for new project (20 min)
↓ Install pre-commit hook from TEMPLATE (10 min)
↓ Create CLAUDE.md from template (15 min)
↓ Ready to go (50 min vs. 8 hours of incident discovery)
```

### Architect Planning Infrastructure
```
"How do we prevent X from happening?"
↓ Search memory: givebutter_e2e_test_incident
↓ Review: TEMPLATE_automation_prevention.md
↓ Design: "We'll use pre-commit hooks + CI checks"
↓ Implement with confidence (based on proven pattern)
```

---

## Evaluation: Did the Learning Work?

**Check if your learning is working:**

- ✅ **Reusability**: Can someone else use this in a different project?
- ✅ **Clarity**: Is the template clear without the original context?
- ✅ **Automation**: Are humans blocked from making the same mistake?
- ✅ **Currency**: Have you updated it with new insights?
- ✅ **Discoverability**: Can someone find this when they need it?

**Red flags:**

- ❌ Incident template is 50 lines (too vague, not actionable)
- ❌ Skill file is just a theory (no code examples)
- ❌ CLAUDE.md exists but no one reads it
- ❌ Pre-commit hook has false positives (developers bypass it)
- ❌ Memory exists but no one knows how to find it

---

## Continuous Improvement

### Quarterly
```
1. Review: Are old incidents still relevant?
2. Update: Have learnings evolved?
3. Consolidate: Do multiple incidents describe the same pattern?
4. Share: Have you told the team about this?
```

### When Similar Issue Appears
```
1. Check memory for similar incident
2. Reference the skill / CLAUDE.md / prevention
3. If prevention exists: Why did it fail?
4. If prevention doesn't exist: Why was it missed?
5. Update memory with lessons
```

### When Onboarding New Team Member
```
1. Point them to CLAUDE.md (5 min read)
2. Have them review incident memory (10 min)
3. Have them read relevant SKILL files (30 min)
4. Have them trigger a pre-commit hook intentionally (5 min)
5. Now they understand "why" behind rules
```

---

## Key Insights

### Learning Compounds
- First incident: 4 hours to solve + 2 hours to document = 6 hours
- Next similar incident: 30 min (have skill + hook blocks it)
- Third incident in different project: 1 hour (copy templates, customize)
- Fourth incident: Mostly solved by hook, minimal human effort

### Prevention Automations Outlive Humans
- Hook installed once, runs forever
- Doesn't need someone to remember
- Works for every developer
- Applies to every commit

### Skill Documents Enable Teaching
- Can onboard faster (leverage existing patterns)
- Can say "read SKILL_X.md" instead of explaining
- Becomes reference material
- Grows with team expertise

### Memory Bridges Conversations
- You can reference incident from months ago
- New team members understand context
- Prevents repeating same conversations
- Becomes organizational knowledge

---

## Remember

**The Goal:** Turn individual learning into collective knowledge that prevents the same mistake indefinitely.

**The Method:**
1. Document what happened (incident memory)
2. Extract generalizable patterns (reusable skill)
3. Define project rules (CLAUDE.md)
4. Automate enforcement (hooks + CI)

**The Result:** Next time someone faces this problem, they're protected automatically.

---

**Next Step:** Pick your most recent complex incident and follow the 4-step process above.

**Questions?** Reference this guide or check the incident memory.

---

**Created:** 2026-06-01  
**Applies to:** Any incident or complex problem  
**Maintenance:** Update quarterly, add examples as you apply templates
