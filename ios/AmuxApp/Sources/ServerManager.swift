import SwiftUI
import Combine

class ServerManager: ObservableObject {
    @Published var serverURL: URL?
    @Published var hasServer: Bool = false

    @Published var savedServers: [SavedServer] {
        didSet {
            if let data = try? JSONEncoder().encode(savedServers) {
                UserDefaults.standard.set(data, forKey: "savedServers")
            }
        }
    }

    init() {
        // Load saved servers
        if let data = UserDefaults.standard.data(forKey: "savedServers"),
           let servers = try? JSONDecoder().decode([SavedServer].self, from: data) {
            self.savedServers = servers
        } else {
            self.savedServers = []
        }

        // Load active server URL
        if let urlString = UserDefaults.standard.string(forKey: "serverURL"),
           let url = URL(string: urlString) {
            self.serverURL = url
            self.hasServer = true
        }
    }

    func selectServer(_ urlString: String) {
        guard let url = URL(string: urlString) else { return }
        serverURL = url
        hasServer = true
        UserDefaults.standard.set(url.absoluteString, forKey: "serverURL")
    }

    func addServer(name: String, urlString: String) -> Bool {
        guard let _ = URL(string: urlString), urlString.hasPrefix("http") else { return false }
        let normalized = urlString.hasSuffix("/") ? String(urlString.dropLast()) : urlString
        // Avoid duplicates
        if !savedServers.contains(where: { $0.url == normalized }) {
            savedServers.append(SavedServer(name: name, url: normalized))
        }
        return true
    }

    func removeServer(at offsets: IndexSet) {
        savedServers.remove(atOffsets: offsets)
    }

    func resetServer() {
        serverURL = nil
        hasServer = false
        UserDefaults.standard.removeObject(forKey: "serverURL")
    }
}

struct SavedServer: Codable, Identifiable {
    var id: String { url }
    let name: String
    let url: String
}
