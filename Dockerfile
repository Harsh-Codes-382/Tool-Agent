FROM postgres:17-alpine

  # Baked into the image — fine for a local/dev sandbox, not for anything
  # that leaves your machine. Override at runtime with -e if you care.
  ENV POSTGRES_PASSWORD=dev

  # Runs ONLY when the data dir is empty (i.e. first start of a fresh volume).
  # Files here execute in alphabetical order, hence the 01_ prefix.
  COPY schema.sql /docker-entrypoint-initdb.d/01_init.sql

  EXPOSE 5432
  # No CMD/ENTRYPOINT needed — the base image's entrypoint handles initdb,
  # runs the seed scripts, then execs the postgres server as PID 1.