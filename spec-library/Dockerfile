FROM golang:1.22-alpine AS builder

WORKDIR /build
COPY src/go.mod src/go.sum ./
RUN go mod download
COPY src/ ./
RUN CGO_ENABLED=0 GOOS=linux go build -o /spec-library .

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=builder /spec-library /usr/local/bin/spec-library
EXPOSE 8080
ENTRYPOINT ["spec-library"]
