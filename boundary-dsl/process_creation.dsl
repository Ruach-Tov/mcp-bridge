# process_creation.dsl — Universal POSIX process creation boundaries
#
# Every process in Unix is created by another process. The creation
# boundary has channels for cwd, fds, envp, argv, and pid.
#
# Two sides:
#   posix_created_process — ABSORBING side (what the created process receives)
#   posix_create_process  — EMITTING side (what the creator sends)
#
# Channel semantics:
#   cwd   — inherited at fork(), implicit, stored in kernel fs_struct
#   fds   — duplicated at fork(), occult, filtered by O_CLOEXEC
#   envp  — curated at fork/exec, semi-explicit, KEY=VALUE block
#   argv  — passed at exec, explicit, the only intentional channel
#   pid   — returned to creator, assigned by kernel to created
#
# A shell is a universal process creation boundary operator — its entire
# purpose is to sit on the emitting side of this boundary repeatedly.
#
# Responsibilities: shell (argv, redirections, cwd, env exports),
# kernel (fork duplicates fds/memory, execve replaces image),
# POSIX (fds 0,1,2 convention, PATH search, O_CLOEXEC).

# ── ABSORBING side — what the created process receives ────────────────
boundary( NAME, :os, PROCESS ) :- posix_created_process( NAME, :os, PROCESS ) ->
  absorb( :argv[] ),
  absorb( :env[] ),
  absorb( :cwd ),
  absorb( :pid ),
  absorb( fd[] ).

# ── EMITTING side — what the creator sends ────────────────────────────
boundary( NAME, A, B ) :- posix_create_process( NAME, A, B )(string command) ->
  emit( pathname( command )),
  emit( argv_tokens( command )),
  emit( :env[] ),
  emit( :cwd ),
  emit( fd[] ),
  absorb( :created_pid ).

# ── DERIVED BOUNDARIES ────────────────────────────────────────────────
# The fd channel of process creation gives rise to the stdio boundary.
# Creator sets up a pipe pair before fork(); the inherited pipe fds
# become stdin/stdout of the created process.
derives(:stdio_boundary, from(:process_creation, channel(:fds)),
  mechanism("pipe() → fork() → close unused ends → stdio boundary")).

# ── MEDIATING ACTORS ─────────────────────────────────────────────────
# Process creation can be mediated by a shell, which interprets an
# opaque command string into structured argv before calling execve().
mediator(:shell, :process_creation,
  transforms(:argv, from(:opaque_shell_string), to(:string_array)),
  mechanism("/bin/sh -c: word splitting, expansion, globbing, quoting → execve()")).

# ── BRIDGE-SPECIFIC PROCESS CREATION ──────────────────────────────────
# The bridge parses CLI options, gathers them into service_args,
# and launches the service_launcher_state_machine.

posix_created_process( :bridge_creation, :os, :bridge ) ->
    :argv[] <- :switches.parse(:os);
    absorb(gather_service_parameter( :service_args, :argv ));
    absorb(gather_log_level( :log_level, :argv ));
    type_assert(consumed(:argv));
    service_launcher_state_machine( :sm1, :service_args).
