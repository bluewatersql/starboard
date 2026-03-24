You must follow all requirements below exactly.

DEVELOPMENT PROCESS
-------------------
0. This project is unreleased and in active development. Changes do not require backwards compatability. There are not consumers or current dependencies, SLAs, etc  on the existing project. 
  - Do not increment version numbers when making changes

1. Use Test-Driven Development (TDD).
   - Maintain >= 80% test coverage for all new or modified modules.

2. Work in isolation.
   - Create a new feature branch (do NOT reuse or extend an existing branch).

3. Follow best practices and current industry standards for all code, tests, documentation, and refactoring.

4. Do not invent features or requirements.
   - If anything is unclear, consult the latest published documentation or ask for clarification before proceeding.

5. No shortcuts and no silent replanning.
   - Every change must follow the defined process end-to-end.

DOCUMENTATION REQUIREMENTS
--------------------------
Place ALL documentation in the untracked local folder:
  /changes/<feature-branch>/

Required documents:
- Architecture and design documentation for the change.
- Progress notes and change logs.
- Fixes, assumptions, and handoff notes.
- One complete final handoff document containing all required context.
  - Remove or clean up any prior handoff documents so only the final version remains.
- Manual testing checklist and test scenarios (when applicable).
- End-user documentation updates (only if relevant).

CODE QUALITY & MAINTENANCE
--------------------------
- Continuously refactor orphaned code, unused functions, outdated tests, and unnecessary dependencies.
- Maintain full backwards compatibility.
  - Perform deep refactoring where necessary to preserve compatibility.
- Avoid over-engineering new features or changes to existing features:
  - Use feature flags only when specified by the design docs
- No technical debt may be introduced.

VALIDATION & CONTROLS
---------------------
- Run all linters and formatters and resolve any warnings or errors:
  - ruff (lint & format)
  - mypy (type-check)
- Zero linting or type-checking errors are permitted.
- All tests must pass before completion.
- No build failures on the main branch are allowed.

COMMIT STRATEGY
---------------
- Before committing ANY changes, ensure that 'make test' runs successfully and that ALL lint and type-check errors are resolved. DO NOT COMMIT without resolving all lint, type-check and test errors.
- Commit changes at the end of each phase or task.
- Use clear, consistent commit messages.
- If the committed changes, add to, update or change the guidance in Claude.md or the .cursor/ folder. Update the project guidance.