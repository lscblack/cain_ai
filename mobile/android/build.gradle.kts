allprojects {
    repositories {
        google()
        mavenCentral()
    }
}

// Flutter expects build output at <flutter project>/build. Set it lazily from
// projectDir (no eager `.get()`), so Gradle does not canonicalize the path to the
// drive's /mnt/<uuid> mount, which previously broke the build.
rootProject.layout.buildDirectory.set(rootProject.projectDir.resolve("../build"))

subprojects {
    project.layout.buildDirectory.set(rootProject.layout.buildDirectory.dir(project.name))
}
subprojects {
    project.evaluationDependsOn(":app")
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
