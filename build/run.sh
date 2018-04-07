#!/bin/bash -e

DIRNAME=$(dirname "$0")


"$DIRNAME/lambdasmushpy/lambdasmushpy.py" \
	--handler-name handler \
	--output "$DIRNAME/../cloudformation/stack.yaml" \
	--source "$DIRNAME/../src/index.py" \
	--strip-comments \
	--strip-empty-lines \
	--template "$DIRNAME/template.yaml" \
	--template-placeholder SMUSH_FUNCTION
