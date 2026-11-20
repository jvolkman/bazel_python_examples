"""Transition a rules_py package target under platform_libc / platform_version flags."""

_FLAGS = [
    "@pypi//dep_group",
    "@rules_py//uv/private/constraints/platform:platform_libc",
    "@rules_py//uv/private/constraints/platform:platform_version",
]

def _transition_impl(settings, attr):
    return {
        "@pypi//dep_group": "wheel-selection-app",
        "@rules_py//uv/private/constraints/platform:platform_libc": attr.libc or settings["@rules_py//uv/private/constraints/platform:platform_libc"],
        "@rules_py//uv/private/constraints/platform:platform_version": attr.version or settings["@rules_py//uv/private/constraints/platform:platform_version"],
    }

_abi_transition = transition(
    implementation = _transition_impl,
    inputs = _FLAGS,
    outputs = _FLAGS,
)

def _transitioned_pkg_impl(ctx):
    return [DefaultInfo(files = ctx.attr.target[0][DefaultInfo].files)]

transitioned_pkg = rule(
    implementation = _transitioned_pkg_impl,
    attrs = {
        "libc": attr.string(),
        "target": attr.label(cfg = _abi_transition),
        "version": attr.string(),
    },
)
