# Parser Framework

The parser framework will provide plugin contracts for format-specific metadata extraction. A parser plugin should declare its supported input types, accept scanner output, and emit normalized metadata events through core interfaces.

Future plugins may support SQL dialects, Informatica PowerCenter, Java, C#, C++, Python, Perl, shell scripts, files, FTP, and REST APIs. Plugins must remain independent of repository implementations.

Sprint 0 creates placeholder packages only. There is no SQL parsing, XML parsing, or AST implementation.