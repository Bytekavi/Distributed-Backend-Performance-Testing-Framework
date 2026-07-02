FROM gcc:14-bookworm AS build
WORKDIR /src
COPY . .
RUN g++ -O3 -std=c++20 -Wall -Wextra -Wpedantic -pthread src/main.cpp -o loadgen

FROM debian:bookworm-slim
COPY --from=build /src/loadgen /usr/local/bin/loadgen
USER 65532:65532
ENTRYPOINT ["loadgen"]

