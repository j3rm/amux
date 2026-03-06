import SwiftUI

@main
struct AmuxApp: App {
    @StateObject private var serverManager = ServerManager()

    var body: some Scene {
        WindowGroup {
            if serverManager.serverURL == nil {
                ServerPickerView()
                    .environmentObject(serverManager)
            } else {
                ContentView()
                    .environmentObject(serverManager)
            }
        }
    }
}
