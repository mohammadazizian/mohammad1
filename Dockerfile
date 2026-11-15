# syntax=docker/dockerfile:1

# The base images can be overridden (registry mirror, corporate images with custom CAs, ...):
#   docker build --build-arg SDK_IMAGE=my-registry/dotnet/sdk:10.0 .
ARG SDK_IMAGE=mcr.microsoft.com/dotnet/sdk:10.0
ARG RUNTIME_IMAGE=mcr.microsoft.com/dotnet/aspnet:10.0

# ---------- Build stage -------------------------------------------------------
FROM ${SDK_IMAGE} AS build
WORKDIR /src

# Copy only the files that define the dependency graph first, so the (slow)
# restore layer is reused until a project file or a package version changes.
COPY Directory.Build.props Directory.Packages.props ./
COPY src/Crm.Domain/Crm.Domain.csproj                 src/Crm.Domain/
COPY src/Crm.Application/Crm.Application.csproj       src/Crm.Application/
COPY src/Crm.Infrastructure/Crm.Infrastructure.csproj src/Crm.Infrastructure/
COPY src/Crm.WebUI/Crm.WebUI.csproj                   src/Crm.WebUI/
RUN dotnet restore src/Crm.WebUI/Crm.WebUI.csproj

COPY src/ src/
RUN dotnet publish src/Crm.WebUI/Crm.WebUI.csproj \
        --configuration Release --no-restore \
        --output /app/publish /p:UseAppHost=false

# ---------- Runtime stage -----------------------------------------------------
FROM ${RUNTIME_IMAGE} AS final
WORKDIR /app

ENV ASPNETCORE_HTTP_PORTS=8080 \
    DOTNET_RUNNING_IN_CONTAINER=true \
    Storage__Path=/app/App_Data/uploads \
    DataProtection__KeysPath=/app/App_Data/keys

# Uploads and data-protection keys live in a volume that the non-root user may write to.
RUN mkdir -p /app/App_Data/uploads /app/App_Data/keys && chown -R "$APP_UID" /app/App_Data
VOLUME ["/app/App_Data"]

COPY --from=build /app/publish .

# Run as the unprivileged user that ships with the official .NET images.
USER $APP_UID
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD bash -c "exec 3<>/dev/tcp/127.0.0.1/8080 && printf 'GET /health HTTP/1.0\r\nHost: localhost\r\n\r\n' >&3 && grep -q ' 200 ' <&3" || exit 1

ENTRYPOINT ["dotnet", "Crm.WebUI.dll"]
