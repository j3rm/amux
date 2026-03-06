import SwiftUI
import WebKit

struct ContentView: View {
    @EnvironmentObject var serverManager: ServerManager
    @State private var isLoading = false
    @State private var canGoBack = false
    @State private var canGoForward = false
    @State private var showSettings = false
    @State private var webViewRef: WKWebView?

    var body: some View {
        NavigationStack {
            ZStack(alignment: .top) {
                if let url = serverManager.serverURL {
                    WebView(
                        url: url,
                        isLoading: $isLoading,
                        canGoBack: $canGoBack,
                        canGoForward: $canGoForward,
                        onNavigationAction: handleNavigation
                    )
                    .ignoresSafeArea(edges: .bottom)
                }

                if isLoading {
                    ProgressView()
                        .progressViewStyle(.linear)
                        .frame(maxWidth: .infinity)
                        .tint(.accentColor)
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItemGroup(placement: .navigationBarLeading) {
                    Button(action: { webViewRef?.goBack() }) {
                        Image(systemName: "chevron.left")
                    }
                    .disabled(!canGoBack)

                    Button(action: { webViewRef?.goForward() }) {
                        Image(systemName: "chevron.right")
                    }
                    .disabled(!canGoForward)
                }

                ToolbarItem(placement: .principal) {
                    Text(serverManager.serverURL?.host ?? "amux")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                ToolbarItem(placement: .navigationBarTrailing) {
                    Button(action: { showSettings = true }) {
                        Image(systemName: "gear")
                    }
                }
            }
        }
        .sheet(isPresented: $showSettings) {
            SettingsView()
                .environmentObject(serverManager)
        }
    }

    private func handleNavigation(_ action: WKNavigationAction) -> WKNavigationActionPolicy {
        // Open external links in Safari
        guard let url = action.request.url,
              let serverHost = serverManager.serverURL?.host else {
            return .allow
        }
        if action.navigationType == .linkActivated && url.host != serverHost {
            UIApplication.shared.open(url)
            return .cancel
        }
        return .allow
    }
}

// MARK: - Settings Sheet

struct SettingsView: View {
    @EnvironmentObject var serverManager: ServerManager
    @Environment(\.dismiss) var dismiss
    @State private var showAddServer = false
    @State private var newName = ""
    @State private var newURL = ""
    @State private var addError = false

    var body: some View {
        NavigationStack {
            List {
                Section("Servers") {
                    ForEach(serverManager.savedServers) { server in
                        HStack {
                            VStack(alignment: .leading) {
                                Text(server.name).font(.headline)
                                Text(server.url).font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            if serverManager.serverURL?.absoluteString == server.url {
                                Image(systemName: "checkmark").foregroundStyle(.accentColor)
                            }
                        }
                        .contentShape(Rectangle())
                        .onTapGesture {
                            serverManager.selectServer(server.url)
                            dismiss()
                        }
                    }
                    .onDelete(perform: serverManager.removeServer)
                }

                Section {
                    Button("Add Server") { showAddServer = true }
                }

                Section {
                    Button("Back to Setup", role: .destructive) {
                        serverManager.resetServer()
                        dismiss()
                    }
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
            .sheet(isPresented: $showAddServer) {
                AddServerView(onAdd: { name, url in
                    if serverManager.addServer(name: name, urlString: url) {
                        showAddServer = false
                    } else {
                        addError = true
                    }
                })
            }
        }
    }
}

// MARK: - Add Server Sheet

struct AddServerView: View {
    @Environment(\.dismiss) var dismiss
    var onAdd: (String, String) -> Void
    @State private var name = ""
    @State private var url = ""
    @State private var showError = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Server Details") {
                    TextField("Name (e.g. Home Mac)", text: $name)
                    TextField("URL (e.g. https://amux.tail-xxxx.ts.net:8822)", text: $url)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                }
                if showError {
                    Section {
                        Text("Invalid URL. Must start with http:// or https://")
                            .foregroundStyle(.red)
                            .font(.caption)
                    }
                }
            }
            .navigationTitle("Add Server")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Add") {
                        showError = false
                        onAdd(name.isEmpty ? url : name, url)
                    }
                    .disabled(url.isEmpty)
                }
            }
        }
    }
}
