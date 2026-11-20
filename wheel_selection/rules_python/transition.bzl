"""Transition a rules_python :whl target under a custom //:target_abi flag."""

def _transition_impl(settings, attr):
    return {"//:target_abi": attr.abi}

_abi_transition = transition(
    implementation = _transition_impl,
    inputs = [],
    outputs = ["//:target_abi"],
)

def _transitioned_whl_impl(ctx):
    return [DefaultInfo(files = ctx.attr.target[0][DefaultInfo].files)]

transitioned_whl = rule(
    implementation = _transitioned_whl_impl,
    attrs = {
        "abi": attr.string(mandatory = True),
        "target": attr.label(cfg = _abi_transition),
    },
)
