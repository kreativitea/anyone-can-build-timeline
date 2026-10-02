# Timeline: short commands for this project. Type `make help` to see them.

# The port `make run` uses. Two worktrees can run at once on two ports:
# `make run PORT=8010`.
PORT ?= 8009

.PHONY: help run test reset worktree

help:
	@echo "make run              start the server (with-backend version), then open http://localhost:$(PORT)"
	@echo "make run PORT=8010    the same, on another port, so two worktrees can run at once"
	@echo "make test             run the checks in with-backend/test_server.py"
	@echo "make reset            delete with-backend/timeline.db, so the timeline starts empty"
	@echo "make worktree BRANCH=name"
	@echo "                      give a branch its own folder, .claude/worktrees/name"
	@echo "                      (a new branch starts from main)"

run:
	cd with-backend && python3 server.py --port $(PORT)

test:
	cd with-backend && python3 -m unittest -v

reset:
	rm -f with-backend/timeline.db

# Every branch gets its own worktree: its own folder, with its own files and
# its own timeline.db, so several people or agents can work at the same time.
worktree:
	@test -n "$(BRANCH)" || { echo "Say which branch: make worktree BRANCH=name"; exit 1; }
	@if git show-ref --quiet --verify refs/heads/$(BRANCH); then \
		git worktree add .claude/worktrees/$(BRANCH) $(BRANCH); \
	else \
		git worktree add -b $(BRANCH) .claude/worktrees/$(BRANCH) main; \
	fi
	@echo "Now work in .claude/worktrees/$(BRANCH)"
