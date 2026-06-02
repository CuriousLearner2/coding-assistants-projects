# TEMPLATE: Prevention Mechanisms & Automation

**Use this template to capture and reuse prevention mechanisms** across projects.

When you solve a problem, automate the prevention so humans don't have to remember.

---

## Overview

| Mechanism | Type | Effort to Install | Maintenance | Effectiveness |
|-----------|------|------------------|-------------|----------------|
| Pre-commit hook | Automation | 10 min | None | Very High |
| Linter rule | Automation | 15 min | Low | High |
| GitHub Actions check | Automation | 30 min | Medium | High |
| Documentation + checklist | Manual | 5 min | Ongoing | Medium |
| Architecture pattern | Design | 20 min | Low | High |

---

## Type 1: Pre-commit Hooks

### When to use:
- Prevent specific code patterns from being committed
- Block files from being modified
- Enforce naming conventions
- Validate syntax before commit

### Template: Block Anti-Pattern

```bash
#!/bin/bash
# .git/hooks/pre-commit
# Purpose: Block [anti-pattern description]
# Incident: [Reference to incident memory]

# Pattern to block
if git diff --cached -- [file_pattern] 2>/dev/null | grep -q "[pattern_to_block]" 2>/dev/null; then
    echo "❌ Error: [User-friendly error message]"
    echo "   Use: [Correct pattern/approach]"
    echo "   Reference: [Documentation link]"
    exit 1
fi

exit 0
```

### Installation:

```bash
# 1. Create hooks directory
mkdir -p .git/hooks

# 2. Save the hook
cat > .git/hooks/pre-commit << 'EOF'
[hook script above]
EOF

# 3. Make executable
chmod +x .git/hooks/pre-commit

# 4. Test it
git commit -m "test"  # Should fail if pattern detected
```

### Example: Block Hidden Selectors (from Givebutter incident)

```bash
#!/bin/bash
# Purpose: Block hidden file input selectors in E2E tests
# Incident: givebutter_e2e_test_incident (2026-06-01)
# Reference: SKILL_RESILIENT_TEST_DESIGN.md

if git diff --cached -- "**/tests/e2e/*.py" 2>/dev/null | grep -q "wait_for_selector('input\[type=\"file\"\]')" 2>/dev/null; then
    echo "❌ Error: Hidden file input selectors detected in staged E2E tests"
    echo "   Use: wait_for_selector('div.drop-zone', timeout=5000)"
    echo "   Reference: SKILL_RESILIENT_TEST_DESIGN.md § Issue 1"
    exit 1
fi

exit 0
```

---

## Type 2: Linter / Format Rules

### When to use:
- Enforce code style
- Prevent unsafe operations
- Validate configuration files
- Catch common mistakes

### Template: ESLint / PyLint Rule

```yaml
# .eslintrc.json / .pylintrc
{
  "rules": {
    "[rule-name]": [
      "error",
      {
        "message": "[User-friendly error message]",
        "reference": "[Documentation link]"
      }
    ]
  }
}
```

### Installation:

```bash
# Python (pylint)
pip install pylint

# JavaScript (eslint)
npm install --save-dev eslint

# Add to CI (see Type 3)
```

---

## Type 3: CI/CD Automation

### When to use:
- Run comprehensive checks on every commit
- Prevent broken code from reaching main
- Generate reports (coverage, performance, etc.)
- Enforce governance (no secrets, no large files)

### Template: GitHub Actions Workflow

```yaml
# .github/workflows/pre-commit.yml
name: Automated Checks

on:
  pull_request:
  push:
    branches: [main]

jobs:
  validate:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up [environment]
        uses: [action]
      
      - name: Run linter
        run: [lint command]
      
      - name: Check for anti-patterns
        run: |
          # Block specific patterns
          if grep -r "[anti-pattern]" [path]; then
            echo "❌ Found forbidden pattern"
            exit 1
          fi
      
      - name: Run tests
        run: [test command]
        timeout-minutes: [X]
      
      - name: Check performance
        run: [performance check]
      
      - name: Report results
        if: always()
        run: [generate report]
```

### Installation:

```bash
# 1. Create workflow directory
mkdir -p .github/workflows

# 2. Save workflow file
cat > .github/workflows/pre-commit.yml << 'EOF'
[workflow above]
EOF

# 3. Push to trigger
git add .github/workflows/pre-commit.yml
git commit -m "Add automated checks"
git push
```

---

## Type 4: Documentation & Checklists

### When to use:
- Capture learnings for humans to follow
- Document design patterns
- Provide troubleshooting guides
- Train new contributors

### Template: Design Checklist

Save this as `.github/CHECKLIST_[domain].md`:

```markdown
# Pre-[Action] Checklist

Use this before [specific action, e.g., committing E2E tests]

## Code Quality
- [ ] Follows [critical requirement 1]
- [ ] Follows [critical requirement 2]
- [ ] No [anti-pattern 1]
- [ ] No [anti-pattern 2]

## Testing
- [ ] Runs locally without timeout
- [ ] Passes [test suite] 
- [ ] Performance acceptable ([metric] < [threshold])
- [ ] No flaky behavior (verified [N] runs)

## Documentation
- [ ] Code is self-explanatory or has comments
- [ ] References related [incident/skill] if applicable
- [ ] Updates [documentation] if behavior changed

## Final Check
- [ ] I read [CLAUDE.md]
- [ ] I checked [relevant incident memory]
- [ ] I ran [verification command]

Reference: [Skill documentation]
Incident: [Related incident memory, if any]
```

---

## Type 5: Monitoring & Alerting

### When to use:
- Detect when prevention breaks down
- Alert on performance degradation
- Track metrics over time
- Identify new patterns early

### Template: Monitoring Script

```bash
#!/bin/bash
# scripts/monitor-health.sh
# Purpose: Monitor key metrics
# Incident: [Reference to incident memory]

THRESHOLD_[METRIC1]=[value]
THRESHOLD_[METRIC2]=[value]

# Check metric 1
ACTUAL_[METRIC1]=$(diagnostic_command_1)
if (( $(echo "$ACTUAL_[METRIC1] > $THRESHOLD_[METRIC1]" | bc -l) )); then
    echo "⚠️  WARNING: [Metric 1] is $ACTUAL_[METRIC1] (threshold: $THRESHOLD_[METRIC1])"
    echo "   This may indicate: [what could be wrong]"
    echo "   Fix: [how to resolve]"
fi

# Check metric 2
ACTUAL_[METRIC2]=$(diagnostic_command_2)
if [[ "$ACTUAL_[METRIC2]" == "[bad value]" ]]; then
    echo "⚠️  WARNING: [Metric 2] failed check"
fi

# Generate report
echo "Health Check Report:"
echo "  Metric 1: $ACTUAL_[METRIC1]"
echo "  Metric 2: $ACTUAL_[METRIC2]"
echo "Reference: [Incident memory / Documentation]"
```

### Installation:

```bash
# 1. Save script
chmod +x scripts/monitor-health.sh

# 2. Run on schedule (cron)
0 9 * * * /path/to/scripts/monitor-health.sh >> health-check.log

# 3. Alert on failure
if [[ $? -ne 0 ]]; then
    # Send alert (Slack, email, etc.)
    curl -X POST [webhook-url] -d "Health check failed"
fi
```

---

## Integration Strategy

### For Small Projects (< 10K lines)

1. **Pre-commit hook** (10 min) ← Start here
2. **CLAUDE.md checklist** (5 min)
3. **Skill documentation** (30 min)

**Total setup time:** ~45 min  
**Effectiveness:** 80%+ at preventing incidents

### For Medium Projects (10K-100K lines)

1. **Pre-commit hook** + **Linter** (20 min)
2. **CLAUDE.md** (10 min)
3. **GitHub Actions CI** (30 min)
4. **Monitoring script** (20 min)
5. **Skill documentation** (30 min)

**Total setup time:** ~2 hours  
**Effectiveness:** 95%+ at preventing incidents

### For Large Projects (> 100K lines)

1. All of above, plus:
2. **Custom GitHub Actions** for domain-specific checks
3. **Metrics dashboard** (Grafana, CloudWatch, etc.)
4. **Incident playbooks** (runbook format)
5. **Quarterly reviews** of prevention effectiveness

**Total setup time:** ~1 week  
**Effectiveness:** 99%+ with continuous improvement

---

## Measuring Effectiveness

### Metrics to Track

```bash
# 1. How often does the prevention trigger?
grep -c "Error:" .git/hooks/pre-commit-logs.txt

# 2. How many incidents would this have prevented?
# (Retrospective: check incident memory)

# 3. How much time saved?
# Time spent fixing incident - Time spent installing prevention

# 4. False positives?
# Developers having to override hook (should be rare)
```

### Success Criteria

- ✅ Hook blocks all instances of anti-pattern
- ✅ Zero false positives (should never block correct code)
- ✅ Easy to bypass if truly necessary (`git commit --no-verify`)
- ✅ Clear error message points to documentation
- ✅ Incident never recurs

---

## Maintenance Playbook

### Quarterly Review

```bash
# 1. Check if prevention is still relevant
# Has the anti-pattern been completely eliminated?
# If yes, can we remove the hook?

# 2. Check metrics
# Are violations still being caught?
# Are false positives increasing?

# 3. Update documentation
# Has the incident memory been referenced by others?
# Should we enhance the skill documentation?

# 4. Escalate if needed
# Is this pattern appearing in other projects?
# Should we create an org-wide enforcement?
```

### If Prevention Gets Outdated

1. **Check if problem still exists:** `[diagnostic command]`
2. **If problem solved:** Remove prevention mechanism
3. **If problem evolved:** Update prevention to catch new pattern
4. **If problem appears elsewhere:** Copy prevention to other projects

---

## Reusable Prevention Mechanisms

### Across Browser Automation Projects
- [Hook: Block hidden selectors](#type-1-pre-commit-hooks)
- [Checklist: E2E test design](#type-4-documentation--checklists)
- [Monitoring: Test execution time](#type-5-monitoring--alerting)

### Across API Testing Projects
- [Hook: Block hardcoded endpoints]
- [Linter: Validate request structure]
- [CI: Run against test server]

### Across Data Pipeline Projects
- [Hook: Block hardcoded secrets]
- [Linter: Validate SQL syntax]
- [Monitoring: Pipeline latency]

---

## Template for New Projects

**When starting a new project, install immediately:**

```bash
# 1. Copy this file and customize
cp TEMPLATE_automation_prevention.md [NEW_PROJECT]/PREVENTION.md

# 2. Create basic pre-commit hook
mkdir -p .git/hooks
cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash
# [Customize based on domain]
exit 0
EOF
chmod +x .git/hooks/pre-commit

# 3. Create CLAUDE.md
cp TEMPLATE_project_claude_md.md CLAUDE.md

# 4. Create incident memory template
cp TEMPLATE_incident_learning_capture.md [incident-name].md
```

---

## Resources

**Pre-commit framework:**
- https://pre-commit.com/ (Language-agnostic hook manager)
- Standardizes hook installation across teams

**Linting tools:**
- Python: pylint, flake8, black
- JavaScript: eslint, prettier
- Go: golangci-lint
- [Find others by language]

**CI/CD platforms:**
- GitHub Actions (free, integrated)
- GitLab CI
- Circle CI
- Jenkins

**Monitoring tools:**
- Prometheus + Grafana
- CloudWatch (AWS)
- Datadog
- New Relic

---

**Version:** 1.0  
**Created:** [YYYY-MM-DD]  
**Last Updated:** [YYYY-MM-DD]  
**Applies To:** [Domain/Technology]  
**Related Incident:** [Link to incident memory]
