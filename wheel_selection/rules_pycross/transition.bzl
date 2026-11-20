"""Transition a wheel target under specific libc / version flags so a host test can inspect it."""

_FLAGS = [
    "@rules_pycross//pycross/settings:glibc_version",
    "@rules_pycross//pycross/settings:musl_version",
    "@rules_python//python/config_settings:py_linux_libc",
]

def _transition_impl(settings, attr):
    return {
        "@rules_pycross//pycross/settings:glibc_version": attr.glibc_version or settings["@rules_pycross//pycross/settings:glibc_version"],
        "@rules_pycross//pycross/settings:musl_version": attr.musl_version or settings["@rules_pycross//pycross/settings:musl_version"],
        "@rules_python//python/config_settings:py_linux_libc": attr.libc or settings["@rules_python//python/config_settings:py_linux_libc"],
    }

_wheel_transition = transition(
    implementation = _transition_impl,
    inputs = _FLAGS,
    outputs = _FLAGS,
)

def _transitioned_wheel_impl(ctx):
    return [DefaultInfo(files = ctx.attr.target[0][DefaultInfo].files)]

transitioned_wheel = rule(
    implementation = _transitioned_wheel_impl,
    attrs = {
        "glibc_version": attr.string(),
        "libc": attr.string(),
        "musl_version": attr.string(),
        "target": attr.label(cfg = _wheel_transition),
    },
)
