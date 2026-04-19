% BPD Prolog IR — generated from process_creation.dsl
% 8 clauses, 0 directives

boundary(NAME, os, PROCESS) :-
    posix_created_process(NAME, os, PROCESS),
    absorb('argv[]'), absorb('env[]'), absorb(cwd), absorb(pid), absorb(fd).

boundary(NAME, A, B) :-
    posix_create_process(NAME, A, B, extra_args(typed(string, command))),
    emit(pathname(command)), emit(argv_tokens(command)), emit('env[]'), emit(cwd), emit(fd), absorb(created_pid).

derives(stdio_boundary, from(process_creation, channel(fds)), mechanism('pipe() → fork() → close unused ends → stdio boundary')).

mediator(shell, process_creation, transforms(argv, from(opaque_shell_string), to(string_array)), mechanism('/bin/sh -c: word splitting, expansion, globbing, quoting → execve()')).

posix_created_process(bridge_creation, os, bridge) :-
    destructure('argv[]', field(switches, parse)), absorb(gather_service_parameter(service_args, argv)).

absorb(gather_log_level(log_level, argv)).

type_assert(consumed(argv)).

service_launcher_state_machine(sm1, service_args).
