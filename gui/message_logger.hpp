#pragma once

#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

namespace rpg {

class MessageLogger {
public:
    void log(std::string msg) {
        if (file_.is_open()) file_ << msg << '\n';
        messages_.push_back(std::move(msg));
    }

    std::vector<std::string> flush() {
        auto out = std::move(messages_);
        messages_.clear();
        return out;
    }

    void setFile(const std::filesystem::path& p) {
        file_.open(p, std::ios::app);
    }

    void closeFile() { file_.close(); }

private:
    std::vector<std::string> messages_;
    std::ofstream file_;
};

} // namespace rpg
