import SwiftUI

struct ServerPickerView: View {
    @EnvironmentObject var serverManager: ServerManager
    @State private var mode: Mode = .choose
    @State private var customURL = ""
    @State private var customName = ""
    @State private var urlError = false

    enum Mode { case choose, custom }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                // Header
                VStack(spacing: 12) {
                    Image(systemName: "square.stack.3d.up.fill")
                        .font(.system(size: 56))
                        .foregroundStyle(.accentColor)
                        .padding(.top, 48)
                    Text("amux")
                        .font(.largeTitle.bold())
                    Text("Where do you run amux?")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                .padding(.bottom, 36)

                // Options
                VStack(spacing: 12) {
                    ServerOptionButton(
                        title: "cloud.amux.io",
                        subtitle: "Managed cloud — sign in with your account",
                        icon: "cloud.fill"
                    ) {
                        serverManager.selectServer("https://cloud.amux.io")
                    }

                    ServerOptionButton(
                        title: "Self-hosted",
                        subtitle: "Your Mac on Tailscale or local network",
                        icon: "desktopcomputer"
                    ) {
                        mode = .custom
                    }
                }
                .padding(.horizontal, 20)

                Spacer()
            }
            .sheet(isPresented: .init(
                get: { mode == .custom },
                set: { if !$0 { mode = .choose } }
            )) {
                NavigationStack {
                    Form {
                        Section {
                            TextField("Name (optional)", text: $customName)
                            TextField("URL — e.g. https://amux.tail-xxxx.ts.net:8822", text: $customURL)
                                .keyboardType(.URL)
                                .autocorrectionDisabled()
                                .textInputAutocapitalization(.never)
                        } header: {
                            Text("Your amux server URL")
                        } footer: {
                            Text("Find your Tailscale hostname in the Tailscale app. Port is 8822 by default.")
                                .font(.caption)
                        }

                        if urlError {
                            Section {
                                Text("Please enter a valid URL starting with http:// or https://")
                                    .foregroundStyle(.red)
                                    .font(.caption)
                            }
                        }
                    }
                    .navigationTitle("Self-hosted Server")
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbar {
                        ToolbarItem(placement: .navigationBarLeading) {
                            Button("Back") { mode = .choose }
                        }
                        ToolbarItem(placement: .navigationBarTrailing) {
                            Button("Connect") {
                                urlError = false
                                let name = customName.isEmpty ? customURL : customName
                                if serverManager.addServer(name: name, urlString: customURL) {
                                    serverManager.selectServer(customURL)
                                } else {
                                    urlError = true
                                }
                            }
                            .disabled(customURL.isEmpty)
                        }
                    }
                }
                .presentationDetents([.medium])
            }
        }
    }
}

// MARK: - Server Option Button

private struct ServerOptionButton: View {
    let title: String
    let subtitle: String
    let icon: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 16) {
                Image(systemName: icon)
                    .font(.title2)
                    .foregroundStyle(.accentColor)
                    .frame(width: 36)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.headline).foregroundStyle(.primary)
                    Text(subtitle).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }
            .padding()
            .background(.secondarySystemGroupedBackground)
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
        .buttonStyle(.plain)
    }
}
