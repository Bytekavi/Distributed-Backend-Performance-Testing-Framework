FROM gcc:14-bookworm AS loadgen-build
WORKDIR /src
COPY load-generator-cpp/ .
RUN g++ -O3 -std=c++20 -Wall -Wextra -Wpedantic -pthread \
    src/main.cpp -o /usr/local/bin/loadgen

FROM maven:3.9.9-eclipse-temurin-21 AS worker-build
WORKDIR /src
COPY worker-java/pom.xml .
RUN mvn -B -q dependency:go-offline
COPY worker-java/src ./src
RUN mvn -B -q package -DskipTests

FROM eclipse-temurin:21-jre-jammy
RUN useradd --system --uid 10001 --create-home worker
WORKDIR /opt/worker
COPY --from=loadgen-build /usr/local/bin/loadgen /usr/local/bin/loadgen
COPY --from=worker-build /src/target/worker.jar ./worker.jar
USER worker

ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75.0", "-jar", "/opt/worker/worker.jar"]

